"""Transactional persistence helpers for order workflows."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import uuid4

import helper
import model
from service.ai_trust import (
    AiTrustEntryGate,
    has_prediction_for_deal,
    is_entry_observation_enabled,
    persist_entry_evaluation,
    schedule_entry_observation,
    schedule_outcome_attribution,
)
from service.database import run_sqlite_write_with_retry
from service.dca_recovery_sizing import (
    LEGACY_SIZING_MODE,
    RecoverySizingPolicy,
    normalize_recovery_sizing_mode,
)
from service.order_payloads import format_trade_datetime, trade_datetime_from_ms
from service.persistence_records import (
    CampaignPersistenceContext,
    ClosedTradePersistenceRecord,
    ClosedTradeSummaryRecord,
    OpenTradeBuyDefaults,
    OpenTradeCreateRecord,
    OpenTradeDcaDefaults,
    OpenTradeLifecycleDefaults,
    OpenTradeUpdateRecord,
    TradeExecutionRecord,
    TradePersistenceRecord,
    UnsellableTradePersistenceRecord,
)
from service.placement_intents import (
    mark_placement_persisted_in_transaction,
    mark_placements_persisted_in_transaction,
)
from service.replay_candles import archive_replay_candles_for_deal
from service.spot_campaign_types import TradeExposureState, TradeLifecycleMode
from service.trade_math import parse_date_to_ms
from tortoise.expressions import F
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger(
    "logs/order_persistence.log", "order_persistence"
)

SUMMARY_TRADE_KEYS = {
    "symbol",
    "deal_id",
    "campaign_id",
    "execution_history_complete",
    "so_count",
    "profit",
    "profit_percent",
    "amount",
    "cost",
    "tp_price",
    "avg_price",
    "open_date",
    "close_date",
    "duration",
    "close_reason",
}

TRADE_ROW_KEYS = {
    "timestamp",
    "ordersize",
    "fee",
    "precision",
    "amount",
    "amount_fee",
    "price",
    "symbol",
    "deal_id",
    "campaign_id",
    "orderid",
    "bot",
    "ordertype",
    "baseorder",
    "safetyorder",
    "order_count",
    "so_percentage",
    "direction",
    "side",
}


def _placement_operation_ids(
    placement_operation_id: str | None,
    placement_operation_ids: Iterable[str] | None,
) -> list[str | None]:
    """Combine the compatibility singular id with composite placement ids."""
    return [
        placement_operation_id,
        *(placement_operation_ids or ()),
    ]


def _create_deal_id() -> str:
    """Return a fresh stable deal identifier."""
    return str(uuid4())


def _parse_order_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return structured metadata attached to an order payload."""
    raw_metadata = payload.get("metadata_json")
    if isinstance(raw_metadata, dict):
        return dict(raw_metadata)
    if not isinstance(raw_metadata, str) or not raw_metadata.strip():
        return {}
    try:
        parsed = json.loads(raw_metadata)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_open_trade_dca_defaults(
    payload: Mapping[str, Any],
) -> OpenTradeDcaDefaults:
    """Extract snapshotted DCA policy state for a newly opened deal."""
    metadata = _parse_order_metadata(payload)
    raw_policy = metadata.get("dca_policy")
    policy = RecoverySizingPolicy.from_dict(
        raw_policy if isinstance(raw_policy, dict) else None
    )
    return {
        "dca_sizing_mode": policy.mode,
        "dca_policy_json": json.dumps(policy.to_dict(), sort_keys=True),
        "dca_reference_price": float(payload.get("price") or 0.0),
        "dca_reference_atr_percent": 0.0,
        "dca_next_trigger_price": 0.0,
        "dca_last_decision_json": None,
    }


def _build_safety_order_dca_updates(
    payload: Mapping[str, Any],
) -> OpenTradeUpdateRecord:
    """Extract recovery decision state from a filled safety order."""
    metadata = _parse_order_metadata(payload)
    raw_decision = metadata.get("recovery_so")
    if not isinstance(raw_decision, dict):
        return {}
    mode = normalize_recovery_sizing_mode(raw_decision.get("mode"))
    if mode == LEGACY_SIZING_MODE:
        return {}
    return {
        "dca_reference_price": float(payload.get("price") or 0.0),
        "dca_reference_atr_percent": float(raw_decision.get("atr_percent") or 0.0),
        "dca_next_trigger_price": 0.0,
        "dca_last_decision_json": json.dumps(raw_decision, sort_keys=True),
    }


def _resolve_buy_execution_role(payload: Mapping[str, Any]) -> str:
    """Return the ledger role for a persisted buy row."""
    if bool(payload.get("baseorder")):
        return "base_order"
    if str(payload.get("orderid") or "").startswith("manual-add-"):
        return "manual_buy"
    if bool(payload.get("safetyorder")):
        return "safety_order"
    return "buy"


def _build_trade_execution_payload(
    deal_id: str,
    payload: Mapping[str, Any],
    *,
    role: str,
) -> TradeExecutionRecord:
    """Normalize a trade-row payload into a TradeExecutions insert payload."""
    return {
        "deal_id": deal_id,
        "campaign_id": payload.get("campaign_id"),
        "symbol": str(payload.get("symbol") or ""),
        "side": str(payload.get("side") or "buy"),
        "role": role,
        "timestamp": str(payload.get("timestamp") or ""),
        "price": float(payload.get("price") or 0.0),
        "amount": float(payload.get("amount") or payload.get("total_amount") or 0.0),
        "ordersize": float(payload.get("ordersize") or 0.0),
        "fee": float(payload.get("fee") or 0.0),
        "order_id": (
            str(payload.get("order_id") or payload.get("orderid"))
            if payload.get("order_id") is not None or payload.get("orderid") is not None
            else None
        ),
        "order_type": (
            str(payload.get("order_type") or payload.get("ordertype"))
            if payload.get("order_type") is not None
            or payload.get("ordertype") is not None
            else None
        ),
        "order_count": payload.get("order_count"),
        "so_percentage": (
            float(payload["so_percentage"])
            if payload.get("so_percentage") is not None
            else None
        ),
        "signal_name": (
            str(payload.get("signal_name"))
            if payload.get("signal_name") is not None
            else None
        ),
        "strategy_name": (
            str(payload.get("strategy_name"))
            if payload.get("strategy_name") is not None
            else None
        ),
        "timeframe": (
            str(payload.get("timeframe"))
            if payload.get("timeframe") is not None
            else None
        ),
        "metadata_json": (
            str(payload.get("metadata_json"))
            if payload.get("metadata_json") is not None
            else None
        ),
    }


def _build_trade_row_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Project persistence metadata onto columns owned by the trades table."""
    return {key: value for key, value in payload.items() if key in TRADE_ROW_KEYS}


async def _resolve_open_deal_state(symbol: str, conn: Any) -> tuple[str, bool]:
    """Return the open deal id and replay completeness flag for a symbol."""
    open_trade = await model.OpenTrades.filter(symbol=symbol).using_db(conn).first()
    if open_trade is None:
        return _create_deal_id(), True

    deal_id = open_trade.deal_id or _create_deal_id()
    if open_trade.deal_id != deal_id:
        await model.OpenTrades.filter(symbol=symbol).using_db(conn).update(
            deal_id=deal_id,
        )
    return deal_id, bool(open_trade.execution_history_complete)


async def _apply_buy_campaign_context(
    conn: Any,
    *,
    symbol: str,
    deal_id: str,
    context: CampaignPersistenceContext | None,
) -> str | None:
    """Persist active campaign state for a buy leg and return campaign id."""
    if not context:
        return None

    campaign_id = str(context.get("campaign_id") or "").strip() or None
    if campaign_id is None:
        return None

    update_payload = {
        "symbol": symbol,
        "lifecycle_mode": str(
            context.get("lifecycle_mode") or TradeLifecycleMode.SIDESTEP_REENTRY.value
        ),
        "state": str(context.get("state") or "active_long"),
        "started_at": str(context.get("started_at") or ""),
        "last_transition_at": str(context.get("last_transition_at") or ""),
        "current_deal_id": deal_id,
        "tp_percent": float(context.get("tp_percent") or 0.0),
        "principal_quote": float(context.get("principal_quote") or 0.0),
        "reserved_quote": float(context.get("reserved_quote") or 0.0),
        "cumulative_realized_quote": float(
            context.get("cumulative_realized_quote") or 0.0
        ),
        "cumulative_realized_percent": float(
            context.get("cumulative_realized_percent") or 0.0
        ),
        "metadata_json": context.get("metadata_json"),
        "cooldown_until": None,
    }
    if bool(context.get("create_campaign")):
        await model.SpotCampaigns.create(
            campaign_id=campaign_id,
            sidestep_count=int(context.get("sidestep_count") or 0),
            last_exit_reason=context.get("last_exit_reason"),
            **update_payload,
            using_db=conn,
        )
    else:
        await model.SpotCampaigns.filter(campaign_id=campaign_id).using_db(conn).update(
            **update_payload,
        )
    return campaign_id


async def _apply_close_campaign_context(
    conn: Any,
    *,
    campaign_id: str | None,
    context: CampaignPersistenceContext | None,
) -> None:
    """Persist campaign transition after a completed sell leg."""
    if not context or not campaign_id:
        return

    update_payload = {
        "state": str(context.get("state") or ""),
        "last_transition_at": str(context.get("last_transition_at") or ""),
        "current_deal_id": None,
        "last_exit_reason": context.get("last_exit_reason"),
        "cooldown_until": context.get("cooldown_until"),
        "tp_percent": float(context.get("tp_percent") or 0.0),
        "reserved_quote": float(context.get("reserved_quote") or 0.0),
        "cumulative_realized_quote": float(
            context.get("cumulative_realized_quote") or 0.0
        ),
        "cumulative_realized_percent": float(
            context.get("cumulative_realized_percent") or 0.0
        ),
        "metadata_json": context.get("metadata_json"),
    }
    if "principal_quote" in context:
        update_payload["principal_quote"] = float(context.get("principal_quote") or 0.0)
    sidestep_increment = int(context.get("sidestep_increment") or 0)
    if sidestep_increment > 0:
        await model.SpotCampaigns.filter(campaign_id=campaign_id).using_db(conn).update(
            sidestep_count=F("sidestep_count") + sidestep_increment,
            **update_payload,
        )
        return
    await model.SpotCampaigns.filter(campaign_id=campaign_id).using_db(conn).update(
        **update_payload,
    )


def _build_open_trade_lifecycle_defaults(
    *,
    campaign_context: CampaignPersistenceContext | None,
    current_deal_id: str,
) -> OpenTradeLifecycleDefaults:
    """Return the canonical live open-trade lifecycle fields for a buy leg."""
    lifecycle_mode = str(
        (campaign_context or {}).get("lifecycle_mode")
        or TradeLifecycleMode.CLASSIC_DCA.value
    )
    return {
        "deal_id": current_deal_id,
        "campaign_id": (
            (campaign_context or {}).get("campaign_id") if campaign_context else None
        ),
        "lifecycle_mode": lifecycle_mode,
        "exposure_state": TradeExposureState.LONG_EXPOSED.value,
        "reserved_reentry_quote": 0.0,
        "waiting_reference_price": 0.0,
        "waiting_reference_amount": 0.0,
        "waiting_reference_quote": 0.0,
        "virtual_waiting_profit": 0.0,
        "virtual_waiting_profit_percent": 0.0,
        "last_transition_at": (
            (campaign_context or {}).get("last_transition_at")
            if campaign_context
            else None
        ),
    }


def _normalize_preserved_open_date(value: Any) -> str | None:
    """Return a stored open date only when it is already parseable."""
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return normalized if parse_date_to_ms(normalized) is not None else None


def _resolve_open_trade_buy_open_date(
    payload: Mapping[str, Any],
    *,
    existing_open_trade: Any | None,
    campaign_context: CampaignPersistenceContext | None,
) -> str | None:
    """Return the stable original open date for a buy-backed open trade row."""
    lifecycle_mode = str(
        (campaign_context or {}).get("lifecycle_mode")
        or getattr(existing_open_trade, "lifecycle_mode", "")
        or TradeLifecycleMode.CLASSIC_DCA.value
    )
    campaign_started_at = _normalize_preserved_open_date(
        (campaign_context or {}).get("started_at")
    )
    existing_open_date = _normalize_preserved_open_date(
        getattr(existing_open_trade, "open_date", None)
    )

    if lifecycle_mode == TradeLifecycleMode.SIDESTEP_REENTRY.value:
        if campaign_started_at:
            return campaign_started_at
        if existing_open_date:
            return existing_open_date
    elif existing_open_date:
        return existing_open_date

    timestamp_raw = payload.get("timestamp")
    if timestamp_raw is None:
        return None
    try:
        return format_trade_datetime(trade_datetime_from_ms(float(timestamp_raw)))
    except (TypeError, ValueError):
        normalized_timestamp = str(timestamp_raw).strip()
        return normalized_timestamp or None


def _build_open_trade_buy_defaults(
    payload: Mapping[str, Any],
    *,
    existing_open_trade: Any | None,
    campaign_context: CampaignPersistenceContext | None,
) -> OpenTradeBuyDefaults:
    """Return immediate open-trade summary fields for a newly filled buy leg."""
    amount = float(payload.get("amount") or 0.0)
    cost = float(payload.get("ordersize") or 0.0)
    avg_price = (
        (cost / amount)
        if amount > 0 and cost > 0
        else float(payload.get("price") or 0.0)
    )
    current_price = float(payload.get("price") or 0.0)
    open_date_value = _resolve_open_trade_buy_open_date(
        payload,
        existing_open_trade=existing_open_trade,
        campaign_context=campaign_context,
    )

    return {
        "so_count": 0,
        "profit": 0.0,
        "profit_percent": 0.0,
        "amount": amount,
        "cost": cost,
        "current_price": current_price,
        "tp_price": 0.0,
        "avg_price": avg_price,
        "open_date": open_date_value,
        **_build_open_trade_dca_defaults(payload),
    }


async def persist_buy_trade(
    symbol: str,
    payload: TradePersistenceRecord,
    *,
    create_open_trade: bool,
    campaign_context: CampaignPersistenceContext | None = None,
    entry_evaluation: AiTrustEntryGate | None = None,
    placement_operation_id: str | None = None,
) -> None:
    """Persist a filled buy trade and create the open-trade row when needed."""

    async def _persist_buy() -> None:
        async with in_transaction() as conn:
            existing_open_trade = (
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).first()
            )
            if create_open_trade:
                deal_id = str(payload.get("deal_id") or _create_deal_id())
                history_complete = True
            else:
                deal_id, history_complete = await _resolve_open_deal_state(symbol, conn)

            campaign_id = await _apply_buy_campaign_context(
                conn,
                symbol=symbol,
                deal_id=deal_id,
                context=campaign_context,
            )
            payload["deal_id"] = deal_id
            payload["campaign_id"] = campaign_id
            await model.Trades.create(
                **_build_trade_row_payload(payload),
                using_db=conn,
            )
            await model.TradeExecutions.create(
                **_build_trade_execution_payload(
                    deal_id,
                    payload,
                    role=_resolve_buy_execution_role(payload),
                ),
                using_db=conn,
            )
            if create_open_trade:
                lifecycle_defaults = _build_open_trade_lifecycle_defaults(
                    campaign_context=(
                        {
                            **(campaign_context or {}),
                            "campaign_id": campaign_id,
                        }
                    ),
                    current_deal_id=deal_id,
                )
                buy_defaults = _build_open_trade_buy_defaults(
                    payload,
                    existing_open_trade=existing_open_trade,
                    campaign_context=campaign_context,
                )
                open_trade_defaults: OpenTradeCreateRecord = {
                    "symbol": symbol,
                    "execution_history_complete": history_complete,
                    **buy_defaults,
                    **lifecycle_defaults,
                }
                if existing_open_trade is None:
                    await model.OpenTrades.create(
                        **open_trade_defaults,
                        using_db=conn,
                    )
                else:
                    update_defaults: OpenTradeUpdateRecord = {
                        **buy_defaults,
                        **lifecycle_defaults,
                    }
                    await model.OpenTrades.filter(symbol=symbol).using_db(conn).update(
                        execution_history_complete=history_complete,
                        sold_amount=0.0,
                        sold_proceeds=0.0,
                        unsellable_amount=0.0,
                        unsellable_reason=None,
                        unsellable_min_notional=None,
                        unsellable_estimated_notional=None,
                        unsellable_since=None,
                        unsellable_notice_sent=False,
                        tp_limit_order_id=None,
                        tp_limit_order_price=None,
                        tp_limit_order_amount=None,
                        tp_limit_order_armed_at=None,
                        **update_defaults,
                    )
            elif campaign_id is not None:
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).update(
                    campaign_id=campaign_id,
                )
            if not create_open_trade:
                dca_updates = _build_safety_order_dca_updates(payload)
                if dca_updates:
                    await model.OpenTrades.filter(symbol=symbol).using_db(conn).update(
                        **dca_updates,
                    )
            await mark_placement_persisted_in_transaction(
                placement_operation_id,
                conn,
            )

    await run_sqlite_write_with_retry(
        _persist_buy, f"persisting buy order for {symbol}"
    )
    try:
        if entry_evaluation is not None and entry_evaluation.evaluated:
            await persist_entry_evaluation(entry_evaluation, payload)
        elif create_open_trade and await is_entry_observation_enabled():
            await schedule_entry_observation(symbol, payload)
    except Exception:
        logging.error(
            "Buy for %s was persisted, but its optional AI trust follow-up failed.",
            symbol,
            exc_info=True,
        )


async def persist_closed_trade(
    symbol: str,
    payload: ClosedTradePersistenceRecord,
    *,
    campaign_context: CampaignPersistenceContext | None = None,
    placement_operation_id: str | None = None,
    placement_operation_ids: Iterable[str] | None = None,
) -> None:
    """Persist a closed trade and remove its open-trade rows."""

    closed_deal_id: str | None = None
    closed_open_date: Any = payload.get("open_date")
    closed_close_date: Any = payload.get("close_date")

    async def _persist_sell() -> None:
        nonlocal closed_close_date, closed_deal_id, closed_open_date
        async with in_transaction() as conn:
            deal_id, history_complete = await _resolve_open_deal_state(symbol, conn)
            closed_deal_id = deal_id
            summary_payload = {
                key: value
                for key, value in payload.items()
                if key in SUMMARY_TRADE_KEYS
            }
            summary_payload["deal_id"] = deal_id
            summary_payload["execution_history_complete"] = history_complete
            summary_payload["campaign_id"] = (
                campaign_context.get("campaign_id")
                if campaign_context
                else payload.get("campaign_id")
            )
            summary_payload["close_reason"] = (
                campaign_context.get("close_reason")
                if campaign_context
                else payload.get("close_reason")
            )
            summary_overrides = (
                campaign_context.get("summary_overrides") if campaign_context else None
            )
            if isinstance(summary_overrides, dict):
                for key, value in summary_overrides.items():
                    if key in SUMMARY_TRADE_KEYS:
                        summary_payload[key] = value
            closed_open_date = summary_payload.get("open_date")
            closed_close_date = summary_payload.get("close_date")
            await model.ClosedTrades.create(**summary_payload, using_db=conn)

            for sell_execution in payload.get("sell_executions") or []:
                if not isinstance(sell_execution, dict):
                    continue
                if float(sell_execution.get("amount") or 0.0) <= 0:
                    continue
                await model.TradeExecutions.create(
                    **_build_trade_execution_payload(
                        deal_id,
                        {
                            **sell_execution,
                            "campaign_id": summary_payload.get("campaign_id"),
                        },
                        role=str(sell_execution.get("role") or "final_sell"),
                    ),
                    using_db=conn,
                )
            await archive_replay_candles_for_deal(
                deal_id,
                symbol,
                open_date=summary_payload.get("open_date"),
                close_date=summary_payload.get("close_date"),
                conn=conn,
            )
            await model.Trades.filter(symbol=symbol).using_db(conn).delete()
            await model.OpenTrades.filter(symbol=symbol).using_db(conn).delete()
            await _apply_close_campaign_context(
                conn,
                campaign_id=str(summary_payload.get("campaign_id") or "").strip()
                or None,
                context=campaign_context,
            )
            await mark_placements_persisted_in_transaction(
                _placement_operation_ids(
                    placement_operation_id,
                    placement_operation_ids,
                ),
                conn,
            )

    await run_sqlite_write_with_retry(
        _persist_sell, f"persisting sell order for {symbol}"
    )
    await _repair_replay_archive_after_commit(
        closed_deal_id,
        symbol,
        open_date=closed_open_date,
        close_date=closed_close_date,
    )
    if await has_prediction_for_deal(closed_deal_id):
        await schedule_outcome_attribution(closed_deal_id)


async def _repair_replay_archive_after_commit(
    deal_id: str | None,
    symbol: str,
    *,
    open_date: Any,
    close_date: Any,
) -> None:
    """Complete a terminal deal's replay archive without holding a DB transaction."""
    if deal_id is None:
        return

    try:
        await archive_replay_candles_for_deal(
            deal_id,
            symbol,
            open_date=open_date,
            close_date=close_date,
            allow_missing_archive_exchange_repair=True,
            allow_live_snapshot_exchange_repair=True,
        )
    except Exception:
        logging.error(
            "Trade %s (%s) was persisted, but replay archive repair failed.",
            symbol,
            deal_id,
            exc_info=True,
        )


async def persist_sidestep_transition(
    symbol: str,
    payload: ClosedTradePersistenceRecord,
    *,
    campaign_context: CampaignPersistenceContext | None = None,
    unsellable_payload: UnsellableTradePersistenceRecord | None = None,
    placement_operation_id: str | None = None,
    placement_operation_ids: Iterable[str] | None = None,
) -> None:
    """Persist a sidestep sell while keeping the active open-trade mission alive."""

    closed_deal_id: str | None = None

    async def _persist_sidestep() -> None:
        nonlocal closed_deal_id
        async with in_transaction() as conn:
            deal_id, history_complete = await _resolve_open_deal_state(symbol, conn)
            closed_deal_id = deal_id
            campaign_id = (
                campaign_context.get("campaign_id")
                if campaign_context
                else payload.get("campaign_id")
            )
            for sell_execution in payload.get("sell_executions") or []:
                if not isinstance(sell_execution, dict):
                    continue
                if float(sell_execution.get("amount") or 0.0) <= 0:
                    continue
                await model.TradeExecutions.create(
                    **_build_trade_execution_payload(
                        deal_id,
                        {
                            **sell_execution,
                            "campaign_id": campaign_id,
                        },
                        role=str(sell_execution.get("role") or "final_sell"),
                    ),
                    using_db=conn,
                )
            await archive_replay_candles_for_deal(
                deal_id,
                symbol,
                open_date=payload.get("open_date"),
                close_date=payload.get("close_date"),
                conn=conn,
            )
            await model.Trades.filter(symbol=symbol).using_db(conn).delete()
            sold_amount = float(payload.get("amount") or 0.0)
            sold_quote = sold_amount * float(payload.get("tp_price") or 0.0)
            await model.OpenTrades.filter(symbol=symbol).using_db(conn).update(
                deal_id=None,
                campaign_id=campaign_id,
                execution_history_complete=history_complete,
                exposure_state=TradeExposureState.FLAT_WAITING_REENTRY.value,
                amount=0.0,
                cost=0.0,
                profit=0.0,
                profit_percent=0.0,
                tp_price=0.0,
                avg_price=0.0,
                sold_amount=0.0,
                sold_proceeds=0.0,
                current_price=float(payload.get("tp_price") or 0.0),
                reserved_reentry_quote=float(
                    (campaign_context or {}).get("reserved_quote") or sold_quote
                ),
                waiting_reference_price=float(payload.get("tp_price") or 0.0),
                waiting_reference_amount=sold_amount,
                waiting_reference_quote=sold_quote,
                virtual_waiting_profit=0.0,
                virtual_waiting_profit_percent=0.0,
                last_transition_at=(
                    (campaign_context or {}).get("last_transition_at")
                    or payload.get("close_date")
                ),
                tp_limit_order_id=None,
                tp_limit_order_price=None,
                tp_limit_order_amount=None,
                tp_limit_order_armed_at=None,
            )
            await _apply_close_campaign_context(
                conn,
                campaign_id=str(campaign_id or "").strip() or None,
                context=campaign_context,
            )
            if unsellable_payload is not None:
                archive_payload = dict(unsellable_payload)
                archive_payload["deal_id"] = deal_id
                archive_payload["execution_history_complete"] = history_complete
                await model.UnsellableTrades.create(
                    **archive_payload,
                    using_db=conn,
                )
            await mark_placements_persisted_in_transaction(
                _placement_operation_ids(
                    placement_operation_id,
                    placement_operation_ids,
                ),
                conn,
            )

    await run_sqlite_write_with_retry(
        _persist_sidestep, f"persisting sidestep transition for {symbol}"
    )
    await _repair_replay_archive_after_commit(
        closed_deal_id,
        symbol,
        open_date=payload.get("open_date"),
        close_date=payload.get("close_date"),
    )


async def persist_manual_buy_add(
    symbol: str,
    trade_payload: TradePersistenceRecord,
    open_trade_payload: OpenTradeUpdateRecord,
) -> None:
    """Persist a manual buy add and update the matching open trade."""

    async def _persist_manual_buy() -> None:
        async with in_transaction() as conn:
            deal_id, history_complete = await _resolve_open_deal_state(symbol, conn)
            trade_payload["deal_id"] = deal_id
            open_trade = (
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).first()
            )
            campaign_id = (
                str(open_trade.campaign_id).strip()
                if open_trade is not None and open_trade.campaign_id
                else None
            )
            trade_payload["campaign_id"] = campaign_id
            await model.Trades.create(
                **_build_trade_row_payload(trade_payload),
                using_db=conn,
            )
            await model.TradeExecutions.create(
                **_build_trade_execution_payload(
                    deal_id,
                    trade_payload,
                    role=_resolve_buy_execution_role(trade_payload),
                ),
                using_db=conn,
            )
            open_trade_payload["deal_id"] = deal_id
            open_trade_payload["campaign_id"] = campaign_id
            open_trade_payload["execution_history_complete"] = history_complete
            updated = (
                await model.OpenTrades.filter(symbol=symbol)
                .using_db(conn)
                .update(**open_trade_payload)
            )
            if updated == 0:
                raise ValueError(f"No open trade found for {symbol}.")

    await run_sqlite_write_with_retry(
        _persist_manual_buy, f"persisting manual buy add for {symbol}"
    )


async def persist_partial_sell_execution(
    symbol: str,
    sold_amount: float,
    sold_proceeds: float,
    sell_executions: Iterable[Mapping[str, Any]] | None = None,
    *,
    placement_operation_id: str | None = None,
    placement_operation_ids: Iterable[str] | None = None,
) -> None:
    """Accumulate partial sell totals and append execution rows."""
    execution_rows = [
        execution
        for execution in (sell_executions or [])
        if isinstance(execution, Mapping)
    ]

    async def _persist_partial_sell_execution() -> None:
        async with in_transaction() as conn:
            open_trade = (
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).first()
            )
            if open_trade is None:
                return

            deal_id = open_trade.deal_id or _create_deal_id()
            campaign_id = (
                str(open_trade.campaign_id).strip() if open_trade.campaign_id else None
            )
            history_complete = bool(open_trade.execution_history_complete) and bool(
                execution_rows
            )
            await model.OpenTrades.filter(symbol=symbol).using_db(conn).update(
                deal_id=deal_id,
                execution_history_complete=history_complete,
                sold_amount=F("sold_amount") + float(sold_amount),
                sold_proceeds=F("sold_proceeds") + float(sold_proceeds),
            )

            ledger_rows = execution_rows or [
                {
                    "symbol": symbol,
                    "side": "sell",
                    "role": "partial_sell",
                    "timestamp": "",
                    "price": (
                        float(sold_proceeds) / float(sold_amount)
                        if float(sold_amount) > 0
                        else 0.0
                    ),
                    "amount": float(sold_amount),
                    "ordersize": float(sold_proceeds),
                    "fee": 0.0,
                }
            ]
            for execution in ledger_rows:
                if float(execution.get("amount") or 0.0) <= 0:
                    continue
                await model.TradeExecutions.create(
                    **_build_trade_execution_payload(
                        deal_id,
                        {
                            **execution,
                            "campaign_id": campaign_id,
                        },
                        role=str(execution.get("role") or "partial_sell"),
                    ),
                    using_db=conn,
                )
            await mark_placements_persisted_in_transaction(
                _placement_operation_ids(
                    placement_operation_id,
                    placement_operation_ids,
                ),
                conn,
            )

    await run_sqlite_write_with_retry(
        _persist_partial_sell_execution,
        f"updating partial sell execution for {symbol}",
    )


async def persist_tp_limit_cancellation(
    symbol: str,
    exchange_status: dict[str, Any] | None,
    *,
    placement_operation_id: str | None = None,
) -> bool:
    """Atomically record a cancel fill, clear TP metadata, and persist intent."""
    status = exchange_status or {}
    filled_amount = max(0.0, float(status.get("filled") or 0.0))
    average_price = float(status.get("average") or status.get("price") or 0.0)
    if (
        filled_amount > 0
        and average_price <= 0
        and float(status.get("cost") or 0.0) > 0
    ):
        average_price = float(status["cost"]) / filled_amount
    proceeds = float(status.get("cost") or filled_amount * average_price)

    async def _persist_tp_limit_cancellation() -> bool:
        async with in_transaction() as conn:
            open_trade = (
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).first()
            )
            if open_trade is None:
                await mark_placement_persisted_in_transaction(
                    placement_operation_id,
                    conn,
                )
                return placement_operation_id is not None

            deal_id = open_trade.deal_id or _create_deal_id()
            campaign_id = (
                str(open_trade.campaign_id).strip() if open_trade.campaign_id else None
            )
            updates: dict[str, Any] = {
                "deal_id": deal_id,
                "tp_limit_order_id": None,
                "tp_limit_order_price": None,
                "tp_limit_order_amount": None,
                "tp_limit_order_armed_at": None,
            }
            if filled_amount > 0:
                updates.update(
                    {
                        "sold_amount": F("sold_amount") + filled_amount,
                        "sold_proceeds": F("sold_proceeds") + proceeds,
                    }
                )
                timestamp = status.get("timestamp")
                await model.TradeExecutions.create(
                    **_build_trade_execution_payload(
                        deal_id,
                        {
                            "symbol": str(status.get("symbol") or symbol),
                            "campaign_id": campaign_id,
                            "side": str(status.get("side") or "sell"),
                            "role": "partial_sell",
                            "timestamp": (
                                str(int(timestamp)) if timestamp is not None else ""
                            ),
                            "price": average_price,
                            "amount": filled_amount,
                            "ordersize": proceeds,
                            "fee": 0.0,
                            "order_id": (
                                str(status.get("id"))
                                if status.get("id") is not None
                                else None
                            ),
                            "order_type": "limit",
                        },
                        role="partial_sell",
                    ),
                    using_db=conn,
                )
            await model.OpenTrades.filter(symbol=symbol).using_db(conn).update(
                **updates
            )
            await mark_placement_persisted_in_transaction(
                placement_operation_id,
                conn,
            )
            return True

    return bool(
        await run_sqlite_write_with_retry(
            _persist_tp_limit_cancellation,
            f"persisting proactive TP cancellation for {symbol}",
        )
    )


async def persist_closed_trade_summary(
    payload: ClosedTradeSummaryRecord,
) -> None:
    """Persist a detached closed-trade summary row without mutating open state."""

    async def _persist_closed_trade_summary() -> None:
        async with in_transaction() as conn:
            await model.ClosedTrades.create(**payload, using_db=conn)

    symbol = str(payload.get("symbol") or "").strip() or "unknown"
    await run_sqlite_write_with_retry(
        _persist_closed_trade_summary,
        f"persisting detached closed trade summary for {symbol}",
    )


async def persist_unsellable_remainder(
    symbol: str,
    payload: UnsellableTradePersistenceRecord,
    *,
    partial_amount: float = 0.0,
    partial_proceeds: float = 0.0,
    sell_executions: Iterable[Mapping[str, Any]] | None = None,
    closed_trade_payload: ClosedTradeSummaryRecord | None = None,
    placement_operation_id: str | None = None,
    placement_operation_ids: Iterable[str] | None = None,
) -> None:
    """Atomically persist a partial close, remainder, and placement state."""
    execution_rows = [
        execution
        for execution in (sell_executions or [])
        if isinstance(execution, Mapping)
    ]

    async def _persist_unsellable_remainder() -> None:
        async with in_transaction() as conn:
            deal_id, history_complete = await _resolve_open_deal_state(symbol, conn)
            open_trade = (
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).first()
            )
            campaign_id = (
                str(open_trade.campaign_id).strip()
                if open_trade is not None and open_trade.campaign_id
                else None
            )
            if partial_amount > 0:
                history_complete = history_complete and bool(execution_rows)
                ledger_rows = execution_rows or [
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "role": "partial_sell",
                        "timestamp": "",
                        "price": (
                            float(partial_proceeds) / float(partial_amount)
                            if float(partial_amount) > 0
                            else 0.0
                        ),
                        "amount": float(partial_amount),
                        "ordersize": float(partial_proceeds),
                        "fee": 0.0,
                    }
                ]
                for execution in ledger_rows:
                    if float(execution.get("amount") or 0.0) <= 0:
                        continue
                    await model.TradeExecutions.create(
                        **_build_trade_execution_payload(
                            deal_id,
                            {
                                **execution,
                                "campaign_id": campaign_id,
                            },
                            role=str(execution.get("role") or "partial_sell"),
                        ),
                        using_db=conn,
                    )

            if closed_trade_payload is not None:
                summary_payload = dict(closed_trade_payload)
                summary_payload["deal_id"] = deal_id
                summary_payload["execution_history_complete"] = history_complete
                await model.ClosedTrades.create(
                    **summary_payload,
                    using_db=conn,
                )

            summary_payload = dict(payload)
            summary_payload["deal_id"] = deal_id
            summary_payload["execution_history_complete"] = history_complete
            await model.UnsellableTrades.create(**summary_payload, using_db=conn)
            await model.Trades.filter(symbol=symbol).using_db(conn).delete()
            await model.OpenTrades.filter(symbol=symbol).using_db(conn).delete()
            await mark_placements_persisted_in_transaction(
                _placement_operation_ids(
                    placement_operation_id,
                    placement_operation_ids,
                ),
                conn,
            )

    await run_sqlite_write_with_retry(
        _persist_unsellable_remainder,
        f"persisting unsellable remainder for {symbol}",
    )


async def persist_stopped_trade(
    symbol: str,
    *,
    campaign_context: CampaignPersistenceContext | None = None,
) -> None:
    """Delete open-trade state for a stopped symbol."""

    async def _persist_stop() -> None:
        async with in_transaction() as conn:
            open_trade = (
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).first()
            )
            await model.OpenTrades.filter(symbol=symbol).using_db(conn).delete()
            await model.Trades.filter(symbol=symbol).using_db(conn).delete()
            await _apply_close_campaign_context(
                conn,
                campaign_id=(
                    str(open_trade.campaign_id).strip()
                    if open_trade is not None and open_trade.campaign_id
                    else None
                ),
                context=campaign_context,
            )
            if open_trade and open_trade.deal_id:
                await model.TradeExecutions.filter(
                    deal_id=open_trade.deal_id,
                ).using_db(conn).delete()

    await run_sqlite_write_with_retry(_persist_stop, f"stopping symbol {symbol}")
