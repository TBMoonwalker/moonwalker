"""DCA trade finalization: persistence, stats, and the trade.buy/trade.sell seams.

Entry-point contract: these functions are called only from DcaOrderLifecycle
and the Orders facade's placement-recovery adapters. The caller guarantees
exclusivity - at runtime by holding the lifecycle_mutation_coordinator lock,
at startup by reconciling before producers start (unconditional acquisition
would deadlock the already-locked bybit recovery path). A persistence error
must not invalidate or notify.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeGuard

import helper
from service.config_views import DcaRuntimeConfigView
from service.dca.dust import DcaDustContext, handle_unsellable_remainder
from service.dca.exchange import DcaExchange
from service.dca.limit_sell import build_partial_status_from_fallback
from service.dca.recovery_sizing import build_recovery_sizing_policy
from service.exchange_types import (
    ExchangeOrderPayload,
    PartialSellStatus,
    SoldCheckStatus,
)
from service.lifecycle_types import normalize_close_reason
from service.monitoring import MonitoringService
from service.order_payloads import (
    build_buy_monitor_payload,
    build_buy_trade_payload,
    build_closed_trade_payloads,
)
from service.order_persistence import (
    persist_buy_trade,
    persist_closed_trade,
    persist_partial_sell_execution,
)
from service.placement_workflow import PlacementWorkflow
from service.trades import Trades
from tortoise.exceptions import ConfigurationError

logging = helper.LoggerFactory.get_logger("logs/dca.log", "dca")

ENTRY_SIZING_RETRY_REASONS = {
    "capital_budget_exceeded",
    "insufficient_quote_balance",
    "invalid_required_quote",
    "invalid_price_or_amount",
}


@dataclass(frozen=True)
class DcaFinalizationContext:
    """Existing Orders dependencies required to finalize DCA trades."""

    trades: Trades
    monitoring: MonitoringService
    placement_workflow: PlacementWorkflow
    exchange: DcaExchange
    utils: helper.Utils


def parse_metadata_json(raw_value: Any) -> dict[str, Any]:
    """Return structured order metadata from a JSON payload when possible."""
    if isinstance(raw_value, dict):
        return dict(raw_value)
    if not isinstance(raw_value, str) or not raw_value.strip():
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_entry_size_retry_order(
    order: dict[str, Any],
    precheck: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a one-shot baseline retry order for entry-sizing failures."""
    if not bool(order.get("baseorder")) or not bool(order.get("entry_size_applied")):
        return None

    reason = str((precheck or {}).get("reason") or "")
    if reason not in ENTRY_SIZING_RETRY_REASONS:
        return None

    baseline_order_size = float(order.get("baseline_order_size") or 0.0)
    current_order_size = float(order.get("ordersize") or 0.0)
    if (
        baseline_order_size <= 0
        or abs(current_order_size - baseline_order_size) < 1e-12
    ):
        return None

    retry_order = dict(order)
    retry_order["ordersize"] = baseline_order_size
    retry_order["entry_size_applied"] = False
    retry_order["entry_size_fallback_applied"] = True
    retry_order["entry_size_fallback_reason"] = reason

    metadata = parse_metadata_json(order.get("metadata_json"))
    entry_sizing = metadata.get("entry_sizing")
    if not isinstance(entry_sizing, dict):
        entry_sizing = {}
    entry_sizing["applied"] = False
    entry_sizing["fallback_applied"] = True
    entry_sizing["fallback_reason_code"] = reason
    entry_sizing["resolved_order_size"] = baseline_order_size
    metadata["entry_sizing"] = entry_sizing
    retry_order["metadata_json"] = json.dumps(metadata, sort_keys=True)
    return retry_order


async def finalize_buy_order(
    order_status: ExchangeOrderPayload,
    config: dict[str, Any],
    *,
    original_order: dict[str, Any],
    dependencies: DcaFinalizationContext,
    placement_operation_id: str | None = None,
) -> bool:
    """Persist a filled buy order and emit monitoring."""
    logging.debug(
        "Finalizing buy symbol=%s order_id=%s",
        order_status.get("symbol"),
        order_status.get("id") or order_status.get("orderid"),
    )
    if not has_valid_buy_fill(order_status):
        logging.error(
            "Skipping trade creation for %s: invalid order status.",
            order_status.get("symbol"),
        )
        return False
    for key in (
        "signal_name",
        "strategy_name",
        "strategy_slug",
        "strategy_version",
        "timeframe",
        "metadata_json",
        "baseline_order_size",
        "entry_size_applied",
        "entry_size_reason_code",
        "entry_size_fallback_applied",
        "entry_size_fallback_reason",
    ):
        if order_status.get(key) is None and original_order.get(key) is not None:
            order_status[key] = original_order[key]
    if bool(order_status.get("safetyorder")):
        metadata = parse_metadata_json(order_status.get("metadata_json"))
        recovery_so = metadata.get("recovery_so")
        if isinstance(recovery_so, dict):
            fill_price = float(order_status.get("price") or 0.0)
            reference_price = float(recovery_so.get("reference_price") or 0.0)
            trigger_market_price = float(recovery_so.get("current_price") or 0.0)
            recovery_so["fill_price"] = fill_price
            if reference_price > 0 and fill_price > 0:
                recovery_so["fill_deviation_percent"] = round(
                    ((fill_price - reference_price) / reference_price) * 100,
                    8,
                )
            if trigger_market_price > 0 and fill_price > 0:
                recovery_so["fill_vs_trigger_percent"] = round(
                    ((fill_price - trigger_market_price) / trigger_market_price) * 100,
                    8,
                )
            metadata["recovery_so"] = recovery_so
            order_status["metadata_json"] = json.dumps(metadata, sort_keys=True)
    if bool(order_status.get("baseorder")):
        metadata = parse_metadata_json(order_status.get("metadata_json"))
        metadata["dca_policy"] = build_recovery_sizing_policy(config).to_dict()
        order_status["metadata_json"] = json.dumps(metadata, sort_keys=True)
        stamp_deal_dca_strategy(order_status, config)
    payload = build_buy_trade_payload(order_status)
    persistence_options: dict[str, Any] = {
        "create_open_trade": not bool(order_status["safetyorder"]),
        "entry_evaluation": original_order.get("_ai_entry_evaluation"),
    }
    if placement_operation_id:
        persistence_options["placement_operation_id"] = placement_operation_id
    await persist_buy_trade(
        order_status["symbol"],
        payload,
        **persistence_options,
    )
    dependencies.placement_workflow.log_persisted(
        placement_operation_id,
        symbol=order_status["symbol"],
        side="buy",
        order_id=str(order_status.get("id") or order_status.get("orderid") or ""),
        amount=str(order_status.get("amount") or "0"),
        quote_cost=str(order_status.get("ordersize") or "0"),
    )
    await reset_unsellable_state(order_status["symbol"], dependencies=dependencies)
    await dependencies.monitoring.notify_trade(
        "trade.buy",
        build_buy_monitor_payload(order_status),
        config,
    )
    return True


def stamp_deal_dca_strategy(
    order_status: ExchangeOrderPayload,
    config: dict[str, Any],
) -> None:
    """Record the active DCA strategy on a strategy-less base order.

    Signal-triggered base orders carry only the optional entry-filter
    strategy. Without the deal's DCA strategy, a dynamic DCA deal that
    never places a safety order has no strategy metadata in the
    execution ledger, so its closed replay would lose the indicator
    overlays shown while the deal was open.
    """
    if order_status.get("strategy_slug") or order_status.get("strategy_name"):
        return
    runtime_config = DcaRuntimeConfigView.from_config(config)
    if not (runtime_config.dynamic_dca and runtime_config.dca_strategy):
        return
    order_status["strategy_name"] = runtime_config.dca_strategy
    order_status["strategy_slug"] = runtime_config.dca_strategy


def log_buy_failure(
    symbol: str,
    precheck: dict[str, Any] | None,
) -> None:
    """Emit the shared failure log for an unfilled buy order."""
    if precheck and not bool(precheck.get("ok", False)):
        logging.warning(
            "Skipping buy order for %s: buy pre-check failed (%s). required=%s available=%s",
            symbol,
            precheck.get("reason", "unknown"),
            precheck.get("required_quote"),
            precheck.get("available_quote"),
        )
        return
    logging.error("Failed creating buy order for %s", symbol)


def is_exchange_order_filled(status: dict[str, Any]) -> bool:
    """Return whether an exchange order status represents a completed fill."""
    order_status = str(status.get("status") or "").lower()
    filled = float(status.get("filled") or 0.0)
    amount = float(status.get("amount") or 0.0)
    return order_status in {"closed", "filled"} or (amount > 0 and filled >= amount)


def is_exchange_order_inactive(status: dict[str, Any]) -> bool:
    """Return whether an exchange order is safely no longer open."""
    order_status = str(status.get("status") or "").lower()
    return order_status in {"canceled", "cancelled", "rejected", "expired"}


def build_tp_limit_sell_payload(
    trades: dict[str, Any],
    exchange_status: dict[str, Any],
    *,
    dependencies: DcaFinalizationContext,
) -> dict[str, Any]:
    """Build a sell payload for a filled proactive TP limit order."""
    fallback_price = float(
        exchange_status.get("average")
        or exchange_status.get("price")
        or trades.get("tp_limit_order_price")
        or trades.get("tp_price")
        or trades.get("current_price")
        or 0.0
    )
    amount = float(
        exchange_status.get("filled")
        or exchange_status.get("amount")
        or trades.get("tp_limit_order_amount")
        or trades.get("total_amount")
        or 0.0
    )
    cost = float(exchange_status.get("cost") or amount * fallback_price)
    timestamp = int(
        exchange_status.get("timestamp") or datetime.now().timestamp() * 1000
    )
    actual_pnl = dependencies.utils.calculate_actual_pnl(trades, fallback_price)
    return {
        "id": str(exchange_status.get("id") or trades["tp_limit_order_id"]),
        "symbol": str(exchange_status.get("symbol") or trades["symbol"]),
        "side": str(exchange_status.get("side") or "sell"),
        "ordertype": str(exchange_status.get("type") or "limit"),
        "amount": amount,
        "total_amount": amount,
        "requested_total_amount": float(
            trades.get("sellable_amount") or trades.get("total_amount") or amount
        ),
        "price": fallback_price,
        "cost": cost,
        "timestamp": timestamp,
        "fee": exchange_status.get("fee") or 0.0,
        "total_cost": float(trades.get("total_cost") or 0.0),
        "actual_pnl": actual_pnl,
    }


async def finalize_completed_sell(
    order_status: SoldCheckStatus,
    config: dict[str, Any],
    *,
    dependencies: DcaFinalizationContext,
    placement_operation_id: str | None = None,
    placement_operation_ids: list[str] | None = None,
) -> None:
    """Persist a completed sell status and emit monitoring."""
    normalized_close_reason = normalize_close_reason(order_status.get("close_reason"))
    order_status["close_reason"] = normalized_close_reason
    close_context = await calculate_closed_trade_stats(
        order_status,
        dependencies=dependencies,
    )
    close_options: dict[str, Any] = {}
    if placement_operation_id:
        close_options["placement_operation_id"] = placement_operation_id
    if placement_operation_ids:
        close_options["placement_operation_ids"] = placement_operation_ids
    await persist_closed_trade(
        order_status["symbol"],
        close_context["payload"],
        **close_options,
    )
    dependencies.placement_workflow.log_persisted(
        placement_operation_id,
        symbol=order_status["symbol"],
        side="sell",
        order_id=str(order_status.get("id") or ""),
        amount=str(
            order_status.get("amount") or order_status.get("total_amount") or "0"
        ),
        quote_cost=str(order_status.get("ordersize") or "0"),
    )
    await dependencies.trades.invalidate_trade_caches()
    await dependencies.monitoring.notify_trade(
        "trade.sell",
        close_context["monitor_payload"],
        config,
    )


async def persist_reconciled_limit_fallback(
    limit_status: dict[str, Any],
    config: dict[str, Any],
    operation_id: str,
    *,
    dependencies: DcaFinalizationContext,
) -> bool:
    """Persist a recovered partial limit fill without replaying fallback."""
    partial_status = build_partial_status_from_fallback(
        limit_status,
        default_symbol=str(limit_status.get("symbol") or ""),
    )
    if float(partial_status.get("partial_filled_amount") or 0.0) <= 0:
        return False
    await handle_partial_sell_status(
        partial_status,
        config,
        dependencies=dependencies,
        placement_operation_id=operation_id,
    )
    return True


async def handle_partial_sell_status(
    order_status: PartialSellStatus,
    config: dict[str, Any],
    *,
    dependencies: DcaFinalizationContext,
    placement_operation_id: str | None = None,
    placement_operation_ids: list[str] | None = None,
) -> None:
    """Persist partial sell execution while keeping the trade open."""
    if bool(order_status.get("unsellable", False)):
        await handle_unsellable_remainder(
            order_status,
            config,
            dependencies=DcaDustContext(
                trades=dependencies.trades,
                monitoring=dependencies.monitoring,
                logger=logging,
                resolve_so_count=lambda symbol: resolve_so_count(
                    symbol, dependencies=dependencies
                ),
                resolve_open_timestamp=lambda symbol: resolve_open_timestamp(
                    symbol, dependencies=dependencies
                ),
            ),
            placement_operation_id=placement_operation_id,
            placement_operation_ids=placement_operation_ids,
        )
        return

    partial_amount = float(order_status.get("partial_filled_amount") or 0.0)
    partial_proceeds = float(order_status.get("partial_proceeds") or 0.0)
    if partial_amount > 0:
        partial_options: dict[str, Any] = {}
        if placement_operation_id:
            partial_options["placement_operation_id"] = placement_operation_id
        if placement_operation_ids:
            partial_options["placement_operation_ids"] = placement_operation_ids
        await persist_partial_sell_execution(
            order_status["symbol"],
            partial_amount,
            partial_proceeds,
            order_status.get("executions"),
            **partial_options,
        )
        await dependencies.trades.invalidate_trade_caches()
        logging.info(
            "Persisted partial sell execution for %s: amount=%s proceeds=%s remaining=%s",
            order_status["symbol"],
            partial_amount,
            partial_proceeds,
            float(order_status.get("remaining_amount") or 0.0),
        )


async def calculate_closed_trade_stats(
    order_status: SoldCheckStatus,
    *,
    dependencies: DcaFinalizationContext,
    partial_amount: float | None = None,
    partial_proceeds: float | None = None,
) -> dict[str, Any]:
    """Build closed-trade payload and monitoring payload.

    When the partial totals are supplied, they are used as the trusted
    bookkeeping and no second read is performed. A stop passes totals it
    read through a fail-closed path, so a transient read error aborts the
    close instead of silently falling back to zero proceeds.
    """
    symbol = order_status["symbol"]
    open_timestamp = await resolve_open_timestamp(symbol, dependencies=dependencies)
    so_count = await resolve_so_count(symbol, dependencies=dependencies)
    if partial_amount is None or partial_proceeds is None:
        (
            partial_amount,
            partial_proceeds,
        ) = await dependencies.trades.get_partial_sell_execution(symbol)

    return build_closed_trade_payloads(
        order_status,
        so_count=so_count,
        open_timestamp_ms=open_timestamp,
        partial_amount=partial_amount or 0.0,
        partial_proceeds=partial_proceeds or 0.0,
    )


async def resolve_open_timestamp(
    symbol: str,
    *,
    dependencies: DcaFinalizationContext,
) -> float:
    """Resolve base-order timestamp for trade duration calculation."""
    base_order = await dependencies.trades.get_trade_by_ordertype(
        symbol, baseorder=True
    )
    try:
        return float(base_order[0]["timestamp"])
    except (IndexError, KeyError, TypeError, ValueError) as e:
        logging.debug("Did not found a timestamp - taking default value. Cause %s", e)
        return datetime.now().timestamp() * 1000


async def resolve_so_count(
    symbol: str,
    *,
    dependencies: DcaFinalizationContext,
) -> int:
    """Resolve safety-order count from open trade row."""
    open_trade = await dependencies.trades.get_open_trades_by_symbol(symbol)
    if open_trade:
        return int(open_trade[0]["so_count"])
    return 0


def is_partial_sell_status(
    order_status: dict[str, Any],
) -> TypeGuard[PartialSellStatus]:
    """Return whether an exchange sell result is a partial-sell status."""
    return str(order_status.get("type") or "") == "partial_sell"


def is_sold_check_status(
    order_status: dict[str, Any],
) -> TypeGuard[SoldCheckStatus]:
    """Return whether an exchange sell result is a finalized sell status."""
    status_type = str(order_status.get("type") or "")
    if status_type == "sold_check":
        return True
    return (
        status_type == ""
        and bool(order_status.get("symbol"))
        and bool(order_status.get("total_amount"))
    )


def has_valid_buy_fill(order_status: ExchangeOrderPayload) -> bool:
    """Validate that an exchange buy payload contains the core filled values."""
    return (
        bool(order_status.get("price"))
        and bool(order_status.get("amount"))
        and (float(order_status["amount"]) > 0)
    )


async def reset_unsellable_state(
    symbol: str,
    *,
    dependencies: DcaFinalizationContext,
) -> None:
    """Clear persisted unsellable markers after a successful buy."""
    try:
        await dependencies.trades.update_open_trades(
            {
                "unsellable_amount": 0.0,
                "unsellable_reason": None,
                "unsellable_min_notional": None,
                "unsellable_estimated_notional": None,
                "unsellable_since": None,
                "unsellable_notice_sent": False,
            },
            symbol,
        )
    except (RuntimeError, ConfigurationError):
        # Tests may stub persistence without initializing DB context.
        pass
