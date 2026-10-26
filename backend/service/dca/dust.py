"""DCA-only dust orchestration over the existing atomic persistence owner.

Confirmed partial fill -> DCA archive context -> atomic persistence -> caches
-> optional notification. A persistence error must not invalidate or notify.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from logging import Logger
from typing import Any

from service.exchange_types import PartialSellStatus
from service.monitoring import MonitoringService
from service.order_close_context import (
    build_unsellable_remainder_context,
    build_unsellable_status_snapshot,
)
from service.order_payloads import trade_datetime_from_ms
from service.order_persistence import persist_unsellable_remainder
from service.trades import Trades


@dataclass(frozen=True)
class DcaDustContext:
    """Existing Orders dependencies required to archive a DCA remainder."""

    trades: Trades
    monitoring: MonitoringService
    logger: Logger
    resolve_so_count: Callable[[str], Awaitable[int]]
    resolve_open_timestamp: Callable[[str], Awaitable[float]]


async def handle_unsellable_remainder(
    order_status: PartialSellStatus,
    config: dict[str, Any],
    *,
    dependencies: DcaDustContext,
    placement_operation_id: str | None = None,
    placement_operation_ids: list[str] | None = None,
) -> None:
    """Record the partial close and archive dust before notifying observers."""
    snapshot = build_unsellable_status_snapshot(order_status)
    if not snapshot.symbol:
        return

    closed_at = resolve_partial_sell_closed_at(order_status)

    open_trade_rows = await dependencies.trades.get_open_trades_by_symbol(
        snapshot.symbol
    )
    open_trade = open_trade_rows[0] if open_trade_rows else None
    so_count = await dependencies.resolve_so_count(snapshot.symbol)
    open_timestamp = (
        await dependencies.resolve_open_timestamp(snapshot.symbol)
        if snapshot.partial_amount > 0
        else None
    )
    context = build_unsellable_remainder_context(
        snapshot,
        open_trade=open_trade,
        so_count=so_count,
        open_timestamp_ms=open_timestamp,
        closed_at=closed_at,
        unsellable_since=closed_at.isoformat(),
    )

    await persist_unsellable_remainder(
        snapshot.symbol,
        context.unsellable_payload,
        partial_amount=context.partial_amount,
        partial_proceeds=context.partial_proceeds,
        sell_executions=snapshot.partial_executions,
        closed_trade_payload=context.closed_trade_payload,
        placement_operation_id=placement_operation_id,
        placement_operation_ids=placement_operation_ids,
    )
    await dependencies.trades.invalidate_trade_caches()

    if not context.already_notified:
        await dependencies.monitoring.notify_trade(
            "trade.unsellable_notional",
            context.monitor_payload,
            config,
        )
    dependencies.logger.warning(
        "Marked %s remainder as unsellable (reason=%s, remaining=%s, min_notional=%s, estimated_notional=%s).",
        context.symbol,
        context.reason,
        context.remaining_amount,
        context.min_notional,
        context.estimated_notional,
    )


def resolve_partial_sell_closed_at(
    order_status: PartialSellStatus,
) -> datetime:
    """Return the best-effort close timestamp for a partial sell status."""
    for execution in order_status.get("executions", []) or []:
        raw_timestamp = execution.get("timestamp")
        if raw_timestamp in (None, ""):
            continue
        try:
            return trade_datetime_from_ms(float(raw_timestamp))
        except (TypeError, ValueError):
            continue
    return datetime.now(timezone.utc)
