"""Shared trading-control helpers for global and mission pause behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import helper
import model
from service.database import run_sqlite_write_with_retry
from service.order_requests import normalize_order_symbol
from service.spot_campaign_types import TradeLifecycleMode
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger(
    "logs/trading_controls.log",
    "trading_controls",
)

GLOBAL_TRADING_PAUSED_KEY = "trading_paused"


def is_global_trading_paused(config: dict[str, Any] | None) -> bool:
    """Return whether Moonwalker is paused for new exposure."""
    return bool((config or {}).get(GLOBAL_TRADING_PAUSED_KEY, False))


def resolve_mission_pause_fields(
    *,
    open_trade: dict[str, Any] | None,
    campaign: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return normalized mission pause fields from existing persistence truth."""
    campaign_lifecycle_mode = str((campaign or {}).get("lifecycle_mode") or "")
    if campaign_lifecycle_mode == TradeLifecycleMode.SIDESTEP_REENTRY.value:
        return {
            "automation_paused": bool((campaign or {}).get("automation_paused", False)),
            "automation_paused_at": (
                str((campaign or {}).get("automation_paused_at") or "").strip() or None
            ),
            "automation_pause_source": "campaign",
        }

    return {
        "automation_paused": bool((open_trade or {}).get("automation_paused", False)),
        "automation_paused_at": (
            str((open_trade or {}).get("automation_paused_at") or "").strip() or None
        ),
        "automation_pause_source": "open_trade" if open_trade else None,
    }


def is_mission_automation_paused(trade_data: dict[str, Any] | None) -> bool:
    """Return whether a resolved mission snapshot is paused."""
    return bool((trade_data or {}).get("automation_paused", False))


@dataclass(frozen=True)
class BuyLikeGateDecision:
    """Explain whether a buy-like action is allowed to proceed."""

    allowed: bool
    reason_code: str | None = None
    message: str | None = None


def evaluate_buy_like_gate(
    *,
    symbol: str,
    config: dict[str, Any] | None,
    trade_data: dict[str, Any] | None = None,
) -> BuyLikeGateDecision:
    """Return whether a buy-like action is currently allowed."""
    normalized_symbol = str(symbol or "").strip().upper()
    if is_global_trading_paused(config):
        return BuyLikeGateDecision(
            allowed=False,
            reason_code="blocked_global_pause",
            message=(
                f"Moonwalker is paused for new exposure. Buy-like actions for "
                f"{normalized_symbol} are blocked until you resume."
            ),
        )

    if is_mission_automation_paused(trade_data):
        return BuyLikeGateDecision(
            allowed=False,
            reason_code="blocked_mission_pause",
            message=(
                f"Automation is paused for {normalized_symbol}. Resume the mission "
                "before adding new exposure."
            ),
        )

    return BuyLikeGateDecision(allowed=True)


@dataclass(frozen=True)
class MissionPauseResult:
    """Typed outcome for pausing or resuming one symbol mission."""

    status: str
    message: str
    symbol: str
    campaign_id: str | None
    automation_paused: bool


class TradingControlsService:
    """Persist and enforce mission-level pause controls."""

    def __init__(self) -> None:
        self._orders: Any | None = None
        self._trades: Any | None = None

    async def _get_orders(self) -> Any:
        """Return the lazily constructed Orders service."""
        if self._orders is None:
            from service.orders import Orders

            self._orders = Orders()
        return self._orders

    async def _get_trades(self) -> Any:
        """Return the lazily constructed Trades service."""
        if self._trades is None:
            from service.trades import Trades

            self._trades = Trades()
        return self._trades

    @staticmethod
    def _utc_now_iso() -> str:
        """Return a stable UTC timestamp for pause transitions."""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Return a normalized BASE/QUOTE symbol or an empty string."""
        try:
            return normalize_order_symbol(symbol)
        except ValueError:
            return ""

    async def _resolve_symbol_mission(self, symbol: str) -> dict[str, Any] | None:
        """Return the persisted mission substrate for a symbol."""
        normalized_symbol = self._normalize_symbol(symbol)
        if not normalized_symbol:
            return None

        open_trade_rows = (
            await model.OpenTrades.filter(symbol=normalized_symbol)
            .limit(1)
            .values(
                "symbol",
                "campaign_id",
                "tp_limit_order_id",
                "automation_paused",
                "automation_paused_at",
            )
        )
        open_trade = open_trade_rows[0] if open_trade_rows else None
        if open_trade is None:
            return None

        campaign_id = str(open_trade.get("campaign_id") or "").strip()
        campaign = None
        if campaign_id:
            campaign_rows = (
                await model.SpotCampaigns.filter(campaign_id=campaign_id)
                .limit(1)
                .values(
                    "campaign_id",
                    "lifecycle_mode",
                    "automation_paused",
                    "automation_paused_at",
                )
            )
            campaign = campaign_rows[0] if campaign_rows else None

        pause_fields = resolve_mission_pause_fields(
            open_trade=open_trade,
            campaign=campaign,
        )
        pause_source = str(pause_fields.get("automation_pause_source") or "")
        return {
            "symbol": normalized_symbol,
            "campaign_id": campaign_id or None,
            "tp_limit_order_id": str(open_trade.get("tp_limit_order_id") or "").strip()
            or None,
            "pause_source": pause_source or "open_trade",
            **pause_fields,
        }

    async def _update_mission_pause_state(
        self,
        *,
        symbol: str,
        pause_source: str,
        campaign_id: str | None,
        paused: bool,
    ) -> bool:
        """Persist one mission pause transition on the correct substrate."""
        paused_at = self._utc_now_iso() if paused else None

        async def _write_pause_state() -> bool:
            async with in_transaction() as conn:
                if pause_source == "campaign" and campaign_id:
                    updated = (
                        await model.SpotCampaigns.filter(campaign_id=campaign_id)
                        .using_db(conn)
                        .update(
                            automation_paused=paused,
                            automation_paused_at=paused_at,
                        )
                    )
                    return updated > 0

                updated = (
                    await model.OpenTrades.filter(symbol=symbol)
                    .using_db(conn)
                    .update(
                        automation_paused=paused,
                        automation_paused_at=paused_at,
                    )
                )
                return updated > 0

        return bool(
            await run_sqlite_write_with_retry(
                _write_pause_state,
                f"{'pausing' if paused else 'resuming'} mission {symbol}",
            )
        )

    async def pause_mission(
        self,
        symbol: str,
        config: dict[str, Any] | None,
    ) -> MissionPauseResult:
        """Pause one symbol mission and cancel any armed proactive TP order."""
        mission = await self._resolve_symbol_mission(symbol)
        if mission is None:
            return MissionPauseResult(
                status="not_found",
                message="Mission not found.",
                symbol=self._normalize_symbol(symbol),
                campaign_id=None,
                automation_paused=False,
            )

        if bool(mission.get("automation_paused", False)):
            return MissionPauseResult(
                status="already_paused",
                message=f"Automation is already paused for {mission['symbol']}.",
                symbol=mission["symbol"],
                campaign_id=mission.get("campaign_id"),
                automation_paused=True,
            )

        if mission.get("tp_limit_order_id"):
            orders = await self._get_orders()
            canceled = await orders.cancel_tp_limit_order(
                mission["symbol"], config or {}
            )
            if not canceled:
                logging.warning(
                    "Mission pause rejected for %s because the proactive TP limit "
                    "order could not be canceled first.",
                    mission["symbol"],
                )
                return MissionPauseResult(
                    status="tp_cancel_failed",
                    message=(
                        f"Could not pause {mission['symbol']} because the proactive "
                        "TP limit order could not be canceled safely."
                    ),
                    symbol=mission["symbol"],
                    campaign_id=mission.get("campaign_id"),
                    automation_paused=False,
                )

        updated = await self._update_mission_pause_state(
            symbol=mission["symbol"],
            pause_source=str(mission.get("pause_source") or "open_trade"),
            campaign_id=mission.get("campaign_id"),
            paused=True,
        )
        if not updated:
            return MissionPauseResult(
                status="not_found",
                message="Mission not found.",
                symbol=mission["symbol"],
                campaign_id=mission.get("campaign_id"),
                automation_paused=False,
            )
        trades = await self._get_trades()
        await trades.invalidate_trade_caches()

        return MissionPauseResult(
            status="paused",
            message=f"Paused automation for {mission['symbol']}.",
            symbol=mission["symbol"],
            campaign_id=mission.get("campaign_id"),
            automation_paused=True,
        )

    async def resume_mission(self, symbol: str) -> MissionPauseResult:
        """Resume one symbol mission without placing any immediate orders."""
        mission = await self._resolve_symbol_mission(symbol)
        if mission is None:
            return MissionPauseResult(
                status="not_found",
                message="Mission not found.",
                symbol=self._normalize_symbol(symbol),
                campaign_id=None,
                automation_paused=False,
            )

        if not bool(mission.get("automation_paused", False)):
            return MissionPauseResult(
                status="already_resumed",
                message=f"Automation is already active for {mission['symbol']}.",
                symbol=mission["symbol"],
                campaign_id=mission.get("campaign_id"),
                automation_paused=False,
            )

        updated = await self._update_mission_pause_state(
            symbol=mission["symbol"],
            pause_source=str(mission.get("pause_source") or "open_trade"),
            campaign_id=mission.get("campaign_id"),
            paused=False,
        )
        if not updated:
            return MissionPauseResult(
                status="not_found",
                message="Mission not found.",
                symbol=mission["symbol"],
                campaign_id=mission.get("campaign_id"),
                automation_paused=True,
            )
        trades = await self._get_trades()
        await trades.invalidate_trade_caches()

        return MissionPauseResult(
            status="resumed",
            message=f"Resumed automation for {mission['symbol']}.",
            symbol=mission["symbol"],
            campaign_id=mission.get("campaign_id"),
            automation_paused=False,
        )
