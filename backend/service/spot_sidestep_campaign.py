"""Spot sidestep campaign runtime and persistence helpers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import helper
import model
from service.config import Config, resolve_timeframe
from service.config_views import SidestepCampaignConfigView
from service.data_timeframes import timeframe_to_seconds
from service.database import run_sqlite_write_with_retry
from service.spot_campaign_types import SpotCampaignState, TradeCloseReason
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger(
    "logs/spot_sidestep_campaign.log",
    "spot_sidestep_campaign",
)


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime into UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat(value: datetime) -> str:
    """Return a stable UTC ISO timestamp."""
    return _ensure_utc(value).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    """Best-effort parse of timestamp-like values."""
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None
    try:
        return _ensure_utc(datetime.fromisoformat(normalized.replace("Z", "+00:00")))
    except ValueError:
        return None


def _parse_metadata(raw_value: Any) -> dict[str, Any]:
    """Return parsed campaign metadata with a dict fallback."""
    if isinstance(raw_value, dict):
        return dict(raw_value)
    if not isinstance(raw_value, str) or not raw_value.strip():
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _serialize_metadata(metadata: dict[str, Any]) -> str:
    """Return compact deterministic metadata JSON."""
    return json.dumps(metadata, sort_keys=True)


def _normalize_symbol(value: Any) -> str:
    """Return a normalized uppercase symbol key."""
    return str(value or "").strip().upper()


@dataclass(frozen=True)
class CampaignAdmissionBlock:
    """Campaign-owned admission state for a symbol."""

    symbol: str
    campaign_id: str
    state: str
    reason_code: str


class SpotSidestepCampaignService:
    """Manage spot sidestep campaigns and flat-waiting re-entry."""

    _instance: SpotSidestepCampaignService | None = None
    _lock = asyncio.Lock()

    REENTRY_LOOP_SECONDS = 5.0
    IDLE_LOOP_SECONDS = 5.0
    REENTRY_RETRY_SECONDS = 30.0

    def __init__(self) -> None:
        """Initialize runtime state and lazy collaborators."""
        self.config: dict[str, Any] = {}
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._watcher_queue: asyncio.Queue[Any] | None = None
        self._orders: Any | None = None
        self._autopilot: Any | None = None
        self._statistic: Any | None = None

    @classmethod
    async def instance(cls) -> "SpotSidestepCampaignService":
        """Return the shared sidestep campaign service instance."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                await cls._instance.init()
            return cls._instance

    async def init(self) -> None:
        """Subscribe to config changes and warm the initial snapshot."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config.snapshot())

    async def start(self) -> None:
        """Start the background waiting-campaign re-entry loop."""
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def shutdown(self) -> None:
        """Stop the background re-entry loop."""
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    def bind_watcher_queue(self, watcher_queue: asyncio.Queue[Any]) -> None:
        """Attach the shared watcher queue used for re-entry symbols."""
        self._watcher_queue = watcher_queue

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Cache the latest config snapshot."""
        self.config = config

    @staticmethod
    def normalize_close_reason(value: Any) -> str:
        """Return a stable close-reason persistence value."""
        normalized = str(value or "").strip().lower()
        if normalized == TradeCloseReason.TRAILING_TAKE_PROFIT.value:
            return TradeCloseReason.TRAILING_TAKE_PROFIT.value
        if normalized == TradeCloseReason.STOP_LOSS.value:
            return TradeCloseReason.STOP_LOSS.value
        if normalized == TradeCloseReason.AUTOPILOT_TIMEOUT.value:
            return TradeCloseReason.AUTOPILOT_TIMEOUT.value
        if normalized == TradeCloseReason.SIDESTEP_EXIT.value:
            return TradeCloseReason.SIDESTEP_EXIT.value
        if normalized == TradeCloseReason.MANUAL_STOP.value:
            return TradeCloseReason.MANUAL_STOP.value
        if normalized == TradeCloseReason.MANUAL_SELL.value:
            return TradeCloseReason.MANUAL_SELL.value
        return TradeCloseReason.TAKE_PROFIT.value

    @staticmethod
    def _campaign_view(config: dict[str, Any] | None) -> SidestepCampaignConfigView:
        """Return the typed sidestep campaign config view."""
        return SidestepCampaignConfigView.from_config(config or {})

    @classmethod
    def is_enabled(cls, config: dict[str, Any] | None) -> bool:
        """Return whether sidestep campaigns are enabled."""
        view = cls._campaign_view(config)
        return view.enabled and view.market == "spot"

    async def _get_orders(self) -> Any:
        """Return the lazily constructed Orders service."""
        if self._orders is None:
            from service.orders import Orders

            self._orders = Orders()
        return self._orders

    async def _get_autopilot(self) -> Any:
        """Return the lazily constructed Autopilot service."""
        if self._autopilot is None:
            from service.autopilot import Autopilot

            self._autopilot = Autopilot()
        return self._autopilot

    async def _get_statistic(self) -> Any:
        """Return the lazily constructed Statistic service."""
        if self._statistic is None:
            from service.statistic import Statistic

            self._statistic = Statistic()
        return self._statistic

    @staticmethod
    def _resolve_cooldown_until(
        *,
        closed_at: datetime,
        config: dict[str, Any],
    ) -> str | None:
        """Return the re-entry cooldown boundary for a sidestep exit."""
        view = SidestepCampaignConfigView.from_config(config)
        candles = int(view.reentry_cooldown_candles)
        if candles <= 0:
            return None

        timeframe_seconds = max(1, timeframe_to_seconds(resolve_timeframe(config)))
        cooldown = _ensure_utc(closed_at) + timedelta(
            seconds=timeframe_seconds * candles
        )
        return _isoformat(cooldown)

    async def _find_symbol_campaign(
        self,
        symbol: str,
        *,
        states: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Return the most recent campaign row for a symbol and optional states."""
        normalized_symbol = _normalize_symbol(symbol)
        if not normalized_symbol:
            return None

        query = model.SpotCampaigns.filter(symbol=normalized_symbol)
        if states:
            query = query.filter(state__in=states)
        rows = await query.order_by("-last_transition_at", "-id").limit(1).values()
        return rows[0] if rows else None

    async def _find_campaign_by_id(self, campaign_id: str) -> dict[str, Any] | None:
        """Return one campaign row by its stable campaign id."""
        normalized_campaign_id = str(campaign_id or "").strip()
        if not normalized_campaign_id:
            return None
        rows = (
            await model.SpotCampaigns.filter(campaign_id=normalized_campaign_id)
            .limit(1)
            .values()
        )
        return rows[0] if rows else None

    async def resolve_buy_context(
        self,
        symbol: str,
        order: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Return campaign context for a persisted buy leg."""
        normalized_symbol = _normalize_symbol(symbol)
        if not normalized_symbol:
            return {"campaign_id": None}

        explicit_campaign_id = str(order.get("campaign_id") or "").strip() or None
        if explicit_campaign_id:
            existing = await self._find_campaign_by_id(explicit_campaign_id)
            metadata = _parse_metadata(
                existing.get("metadata_json") if existing else None
            )
            metadata.pop("last_reentry_error", None)
            return {
                "campaign_id": explicit_campaign_id,
                "create_campaign": existing is None,
                "state": SpotCampaignState.ACTIVE_LONG.value,
                "started_at": (
                    existing.get("started_at") if existing else _isoformat(_utc_now())
                ),
                "last_transition_at": _isoformat(_utc_now()),
                "tp_percent": float(
                    (existing or {}).get("tp_percent") or config.get("tp") or 0.0
                ),
                "metadata_json": _serialize_metadata(metadata),
            }

        if bool(order.get("safetyorder")) and not bool(order.get("baseorder")):
            open_trade_rows = (
                await model.OpenTrades.filter(symbol=normalized_symbol)
                .limit(1)
                .values("campaign_id")
            )
            open_trade = open_trade_rows[0] if open_trade_rows else None
            campaign_id = str((open_trade or {}).get("campaign_id") or "").strip()
            if campaign_id:
                return {"campaign_id": campaign_id}
            active_campaign = await self._find_symbol_campaign(
                normalized_symbol,
                states=[SpotCampaignState.ACTIVE_LONG.value],
            )
            if active_campaign:
                return {"campaign_id": active_campaign["campaign_id"]}
            return {"campaign_id": None}

        existing_campaign = await self._find_symbol_campaign(
            normalized_symbol,
            states=[
                SpotCampaignState.ACTIVE_LONG.value,
                SpotCampaignState.FLAT_WAITING_REENTRY.value,
            ],
        )
        if existing_campaign:
            metadata = _parse_metadata(existing_campaign.get("metadata_json"))
            metadata.pop("last_reentry_error", None)
            return {
                "campaign_id": existing_campaign["campaign_id"],
                "create_campaign": False,
                "state": SpotCampaignState.ACTIVE_LONG.value,
                "started_at": existing_campaign.get("started_at")
                or _isoformat(_utc_now()),
                "last_transition_at": _isoformat(_utc_now()),
                "tp_percent": float(
                    existing_campaign.get("tp_percent") or config.get("tp") or 0.0
                ),
                "metadata_json": _serialize_metadata(metadata),
            }

        if not self.is_enabled(config):
            return {"campaign_id": None}

        return {
            "campaign_id": str(uuid4()),
            "create_campaign": True,
            "state": SpotCampaignState.ACTIVE_LONG.value,
            "started_at": _isoformat(_utc_now()),
            "last_transition_at": _isoformat(_utc_now()),
            "tp_percent": float(config.get("tp") or 0.0),
            "metadata_json": _serialize_metadata({}),
        }

    async def resolve_close_context(
        self,
        symbol: str,
        close_reason: str,
        config: dict[str, Any],
        *,
        closed_at: datetime,
    ) -> dict[str, Any]:
        """Return campaign transition context for a persisted sell leg."""
        normalized_symbol = _normalize_symbol(symbol)
        if not normalized_symbol:
            return {"campaign_id": None, "close_reason": close_reason}

        open_trade_rows = (
            await model.OpenTrades.filter(symbol=normalized_symbol)
            .limit(1)
            .values("campaign_id")
        )
        open_trade = open_trade_rows[0] if open_trade_rows else None
        campaign_id = str((open_trade or {}).get("campaign_id") or "").strip()
        campaign = None
        if campaign_id:
            campaign = await self._find_campaign_by_id(campaign_id)
        if campaign is None:
            campaign = await self._find_symbol_campaign(normalized_symbol)

        normalized_reason = self.normalize_close_reason(close_reason)
        if campaign is None:
            return {
                "campaign_id": None,
                "close_reason": normalized_reason,
            }

        metadata = _parse_metadata(campaign.get("metadata_json"))
        metadata["last_close_reason"] = normalized_reason
        metadata["last_closed_at"] = _isoformat(closed_at)

        if normalized_reason == TradeCloseReason.SIDESTEP_EXIT.value:
            metadata["last_exit_at"] = _isoformat(closed_at)
            return {
                "campaign_id": campaign["campaign_id"],
                "close_reason": normalized_reason,
                "state": SpotCampaignState.FLAT_WAITING_REENTRY.value,
                "last_transition_at": _isoformat(closed_at),
                "last_exit_reason": normalized_reason,
                "cooldown_until": self._resolve_cooldown_until(
                    closed_at=closed_at,
                    config=config,
                ),
                "sidestep_increment": 1,
                "tp_percent": float(
                    campaign.get("tp_percent") or config.get("tp") or 0.0
                ),
                "metadata_json": _serialize_metadata(metadata),
            }

        next_state = SpotCampaignState.STOPPED.value
        if normalized_reason in {
            TradeCloseReason.TAKE_PROFIT.value,
            TradeCloseReason.TRAILING_TAKE_PROFIT.value,
        }:
            next_state = SpotCampaignState.COMPLETED_TP.value

        return {
            "campaign_id": campaign["campaign_id"],
            "close_reason": normalized_reason,
            "state": next_state,
            "last_transition_at": _isoformat(closed_at),
            "last_exit_reason": normalized_reason,
            "cooldown_until": None,
            "sidestep_increment": 0,
            "tp_percent": float(campaign.get("tp_percent") or config.get("tp") or 0.0),
            "metadata_json": _serialize_metadata(metadata),
        }

    async def ensure_campaign_for_open_trade(
        self,
        trade_data: dict[str, Any],
        config: dict[str, Any],
    ) -> str | None:
        """Attach a campaign to an already-open trade when sidestep becomes enabled."""
        if not self.is_enabled(config):
            return None

        symbol = _normalize_symbol(trade_data.get("symbol"))
        if not symbol:
            return None

        existing_open_trade_rows = (
            await model.OpenTrades.filter(symbol=symbol)
            .limit(1)
            .values("campaign_id", "deal_id", "open_date")
        )
        existing_open_trade = (
            existing_open_trade_rows[0] if existing_open_trade_rows else None
        )
        if existing_open_trade and existing_open_trade.get("campaign_id"):
            return str(existing_open_trade["campaign_id"])

        campaign = await self._find_symbol_campaign(
            symbol,
            states=[SpotCampaignState.ACTIVE_LONG.value],
        )
        campaign_id = str((campaign or {}).get("campaign_id") or uuid4())
        started_at = str(
            (existing_open_trade or {}).get("open_date")
            or trade_data.get("open_date")
            or _isoformat(_utc_now())
        )
        deal_id = (
            str(
                (existing_open_trade or {}).get("deal_id")
                or trade_data.get("deal_id")
                or ""
            ).strip()
            or None
        )
        last_transition_at = _isoformat(_utc_now())

        async def _attach_campaign() -> None:
            async with in_transaction() as conn:
                if campaign is None:
                    await model.SpotCampaigns.create(
                        campaign_id=campaign_id,
                        symbol=symbol,
                        state=SpotCampaignState.ACTIVE_LONG.value,
                        started_at=started_at,
                        last_transition_at=last_transition_at,
                        current_deal_id=deal_id,
                        sidestep_count=0,
                        last_exit_reason=None,
                        cooldown_until=None,
                        tp_percent=float(config.get("tp") or 0.0),
                        metadata_json=_serialize_metadata({}),
                        using_db=conn,
                    )
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).update(
                    campaign_id=campaign_id,
                )
                await model.Trades.filter(symbol=symbol).using_db(conn).update(
                    campaign_id=campaign_id,
                )
                if deal_id:
                    await model.TradeExecutions.filter(deal_id=deal_id).using_db(
                        conn
                    ).update(campaign_id=campaign_id)

        await run_sqlite_write_with_retry(
            _attach_campaign,
            f"attaching sidestep campaign for {symbol}",
        )
        return campaign_id

    async def record_long_signal(
        self,
        symbol: str,
        *,
        signal_name: str | None,
        strategy_name: str | None,
        timeframe: str | None,
        metadata_json: str | None,
        source: str,
    ) -> None:
        """Persist the latest fresh long signal for a waiting campaign."""
        normalized_symbol = _normalize_symbol(symbol)
        campaign = await self._find_symbol_campaign(
            normalized_symbol,
            states=[SpotCampaignState.FLAT_WAITING_REENTRY.value],
        )
        if campaign is None:
            return

        signal_timestamp = _isoformat(_utc_now())
        metadata = _parse_metadata(campaign.get("metadata_json"))
        metadata["last_long_signal_at"] = signal_timestamp
        metadata["last_long_signal_context"] = {
            "signal_name": signal_name,
            "strategy_name": strategy_name,
            "timeframe": timeframe,
            "metadata_json": metadata_json,
            "source": source,
        }

        await model.SpotCampaigns.filter(campaign_id=campaign["campaign_id"]).update(
            metadata_json=_serialize_metadata(metadata),
            last_transition_at=str(
                campaign.get("last_transition_at") or signal_timestamp
            ),
        )

    async def get_admission_blocks(
        self,
        symbols: list[str],
    ) -> dict[str, CampaignAdmissionBlock]:
        """Return campaign-owned admission blocks for the given symbols."""
        normalized_symbols = [
            normalized
            for normalized in {_normalize_symbol(symbol) for symbol in symbols}
            if normalized
        ]
        if not normalized_symbols:
            return {}

        rows = await model.SpotCampaigns.filter(
            symbol__in=normalized_symbols,
            state__in=[
                SpotCampaignState.ACTIVE_LONG.value,
                SpotCampaignState.FLAT_WAITING_REENTRY.value,
            ],
        ).values("symbol", "campaign_id", "state", "last_transition_at")

        latest_by_symbol: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = _normalize_symbol(row.get("symbol"))
            previous = latest_by_symbol.get(symbol)
            if previous is None or str(row.get("last_transition_at") or "") > str(
                previous.get("last_transition_at") or ""
            ):
                latest_by_symbol[symbol] = row

        blocks: dict[str, CampaignAdmissionBlock] = {}
        for symbol, row in latest_by_symbol.items():
            state = str(row.get("state") or "")
            reason_code = (
                "skipped_campaign_waiting_reentry"
                if state == SpotCampaignState.FLAT_WAITING_REENTRY.value
                else "skipped_campaign_active_long"
            )
            blocks[symbol] = CampaignAdmissionBlock(
                symbol=symbol,
                campaign_id=str(row.get("campaign_id") or ""),
                state=state,
                reason_code=reason_code,
            )
        return blocks

    def _waiting_gate(
        self,
        campaign: dict[str, Any],
        config: dict[str, Any],
    ) -> tuple[str, str]:
        """Return gate status and detail for a waiting campaign."""
        metadata = _parse_metadata(campaign.get("metadata_json"))
        now = _utc_now()

        last_attempt_at = _parse_datetime(metadata.get("last_reentry_attempt_at"))
        if (
            last_attempt_at is not None
            and (now - last_attempt_at).total_seconds() < self.REENTRY_RETRY_SECONDS
        ):
            return ("retry_backoff", "Waiting before the next re-entry attempt.")

        cooldown_until = _parse_datetime(campaign.get("cooldown_until"))
        if cooldown_until is not None and cooldown_until > now:
            return ("cooldown", "Waiting for re-entry cooldown to expire.")

        signal_context = metadata.get("last_long_signal_context")
        if not isinstance(signal_context, dict):
            return ("awaiting_long_signal", "Waiting for a fresh long signal.")

        last_long_signal_at = _parse_datetime(metadata.get("last_long_signal_at"))
        last_exit_at = _parse_datetime(metadata.get("last_exit_at")) or _parse_datetime(
            campaign.get("last_transition_at")
        )
        view = SidestepCampaignConfigView.from_config(config)
        if (
            view.reentry_requires_fresh_long_signal
            and last_long_signal_at is not None
            and last_exit_at is not None
            and last_long_signal_at <= last_exit_at
        ):
            return (
                "awaiting_fresh_long_signal",
                "Waiting for a long signal newer than the sidestep exit.",
            )
        return ("ready", "Eligible for re-entry.")

    async def get_waiting_campaign_summaries(self) -> list[dict[str, Any]]:
        """Return compact waiting-campaign summaries for dashboard display."""
        rows = (
            await model.SpotCampaigns.filter(
                state=SpotCampaignState.FLAT_WAITING_REENTRY.value,
            )
            .order_by("symbol", "-last_transition_at")
            .values()
        )

        summaries: list[dict[str, Any]] = []
        for row in rows:
            gate_status, gate_detail = self._waiting_gate(row, self.config)
            metadata = _parse_metadata(row.get("metadata_json"))
            summaries.append(
                {
                    "campaign_id": row["campaign_id"],
                    "symbol": row["symbol"],
                    "state": row["state"],
                    "sidestep_count": int(row.get("sidestep_count") or 0),
                    "last_exit_reason": row.get("last_exit_reason"),
                    "cooldown_until": row.get("cooldown_until"),
                    "last_transition_at": row.get("last_transition_at"),
                    "tp_percent": float(row.get("tp_percent") or 0.0),
                    "gate_status": gate_status,
                    "gate_detail": gate_detail,
                    "last_long_signal_at": metadata.get("last_long_signal_at"),
                }
            )
        return summaries

    async def stop_campaign(self, campaign_id: str) -> bool:
        """Stop a waiting or active campaign manually."""
        normalized_campaign_id = str(campaign_id or "").strip()
        if not normalized_campaign_id:
            return False

        updated = await model.SpotCampaigns.filter(
            campaign_id=normalized_campaign_id,
            state__in=[
                SpotCampaignState.ACTIVE_LONG.value,
                SpotCampaignState.FLAT_WAITING_REENTRY.value,
            ],
        ).update(
            state=SpotCampaignState.STOPPED.value,
            last_transition_at=_isoformat(_utc_now()),
            last_exit_reason=TradeCloseReason.MANUAL_STOP.value,
            cooldown_until=None,
        )
        return updated > 0

    async def _run_loop(self) -> None:
        """Continuously try re-entry for eligible waiting campaigns."""
        while self._running:
            interval = self.IDLE_LOOP_SECONDS
            try:
                if self.is_enabled(self.config):
                    await self._process_waiting_reentries()
                    interval = self.REENTRY_LOOP_SECONDS
            except Exception as exc:  # noqa: BLE001 - keep loop alive.
                logging.error(
                    "Sidestep campaign refresh failed: %s", exc, exc_info=True
                )
            await asyncio.sleep(interval)

    async def _process_waiting_reentries(self) -> None:
        """Re-enter eligible waiting campaigns from recorded long signals."""
        waiting_campaigns = (
            await model.SpotCampaigns.filter(
                state=SpotCampaignState.FLAT_WAITING_REENTRY.value,
            )
            .order_by("last_transition_at")
            .values()
        )

        for campaign in waiting_campaigns:
            gate_status, _gate_detail = self._waiting_gate(campaign, self.config)
            if gate_status != "ready":
                continue
            await self._attempt_reentry(campaign)

    async def _attempt_reentry(self, campaign: dict[str, Any]) -> None:
        """Attempt one sidestep re-entry buy for a waiting campaign."""
        symbol = _normalize_symbol(campaign.get("symbol"))
        if not symbol:
            return

        existing_open = await model.OpenTrades.filter(symbol=symbol).exists()
        if existing_open:
            return

        metadata = _parse_metadata(campaign.get("metadata_json"))
        signal_context = metadata.get("last_long_signal_context")
        if not isinstance(signal_context, dict):
            return

        statistic = await self._get_statistic()
        autopilot = await self._get_autopilot()
        from service.signal_runtime import resolve_signal_entry_orders

        entry_orders = await resolve_signal_entry_orders(
            self.config,
            statistic,
            autopilot,
            [symbol],
            signal_name=(
                str(signal_context.get("signal_name"))
                if signal_context.get("signal_name") is not None
                else None
            ),
            strategy_name=(
                str(signal_context.get("strategy_name"))
                if signal_context.get("strategy_name") is not None
                else None
            ),
            timeframe=(
                str(signal_context.get("timeframe"))
                if signal_context.get("timeframe") is not None
                else resolve_timeframe(self.config)
            ),
        )
        entry_order = entry_orders.get(symbol)
        if entry_order is None:
            return

        metadata["last_reentry_attempt_at"] = _isoformat(_utc_now())
        await model.SpotCampaigns.filter(campaign_id=campaign["campaign_id"]).update(
            metadata_json=_serialize_metadata(metadata),
        )

        if self._watcher_queue is not None:
            await self._watcher_queue.put([symbol])

        order = {
            "ordersize": entry_order.order_size,
            "symbol": symbol,
            "direction": "long",
            "botname": f"sidestep_{symbol}",
            "baseorder": True,
            "safetyorder": False,
            "order_count": 0,
            "ordertype": "market",
            "so_percentage": None,
            "side": "buy",
            "campaign_id": campaign["campaign_id"],
            "signal_name": entry_order.signal_name,
            "strategy_name": entry_order.strategy_name,
            "timeframe": entry_order.timeframe,
            "metadata_json": entry_order.metadata_json,
            "baseline_order_size": entry_order.baseline_order_size,
            "entry_size_applied": entry_order.entry_size_applied,
            "entry_size_reason_code": entry_order.reason_code,
            "entry_size_fallback_applied": False,
            "entry_size_fallback_reason": None,
        }
        orders = await self._get_orders()
        success = await orders.receive_buy_order(order, self.config)
        if success:
            return

        metadata["last_reentry_error"] = "buy_rejected"
        await model.SpotCampaigns.filter(campaign_id=campaign["campaign_id"]).update(
            metadata_json=_serialize_metadata(metadata),
        )
