"""Pure helpers for partial sell and unsellable remainder close flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from service.exchange_types import PartialSellStatus, TradeExecutionPayload
from service.order_payloads import calculate_trade_duration


@dataclass(frozen=True)
class UnsellableStatusSnapshot:
    """Normalized unsellable partial-sell status values."""

    symbol: str
    partial_amount: float
    partial_proceeds: float
    remaining_amount: float
    reason: str
    min_notional: float | None
    estimated_notional: float | None
    partial_executions: tuple[TradeExecutionPayload, ...]


@dataclass(frozen=True)
class UnsellableRemainderContext:
    """Calculated payloads and notification data for an unsellable remainder."""

    symbol: str
    partial_amount: float
    partial_proceeds: float
    remaining_amount: float
    reason: str
    min_notional: float | None
    estimated_notional: float | None
    already_notified: bool
    closed_trade_payload: dict[str, Any] | None
    unsellable_payload: dict[str, Any]
    monitor_payload: dict[str, Any]


def build_unsellable_status_snapshot(
    order_status: PartialSellStatus,
) -> UnsellableStatusSnapshot:
    """Normalize partial sell status values for unsellable remainder handling."""
    min_notional_raw = order_status.get("unsellable_min_notional")
    estimated_notional_raw = order_status.get("unsellable_estimated_notional")
    return UnsellableStatusSnapshot(
        symbol=str(order_status.get("symbol") or ""),
        partial_amount=max(
            0.0,
            float(order_status.get("partial_filled_amount") or 0.0),
        ),
        partial_proceeds=max(
            0.0,
            float(order_status.get("partial_proceeds") or 0.0),
        ),
        remaining_amount=max(
            0.0,
            float(order_status.get("remaining_amount") or 0.0),
        ),
        reason=str(order_status.get("unsellable_reason") or "minimum_notional"),
        min_notional=(
            float(min_notional_raw) if min_notional_raw is not None else None
        ),
        estimated_notional=(
            float(estimated_notional_raw)
            if estimated_notional_raw is not None
            else None
        ),
        partial_executions=tuple(
            execution
            for execution in order_status.get("executions", [])
            if isinstance(execution, dict)
        ),
    )


def build_unsellable_remainder_context(
    snapshot: UnsellableStatusSnapshot,
    *,
    open_trade: dict[str, Any] | None,
    so_count: int,
    open_timestamp_ms: float | None = None,
    closed_at: datetime | None = None,
    unsellable_since: str | None = None,
) -> UnsellableRemainderContext:
    """Build persistence and notification context for an unsellable remainder."""
    already_notified = bool(open_trade and open_trade.get("unsellable_notice_sent"))
    total_amount = float(open_trade.get("amount") or 0.0) if open_trade else 0.0
    total_cost = float(open_trade.get("cost") or 0.0) if open_trade else 0.0
    avg_buy_price = (total_cost / total_amount) if total_amount > 0 else 0.0
    sold_cost = avg_buy_price * snapshot.partial_amount
    remaining_cost = max(0.0, total_cost - sold_cost)
    current_price = float(open_trade.get("current_price") or 0.0) if open_trade else 0.0
    deal_id = str(open_trade.get("deal_id") or "") if open_trade else ""
    execution_history_complete = bool(
        open_trade.get("execution_history_complete", True) if open_trade else True
    )
    remaining_profit = current_price * snapshot.remaining_amount - remaining_cost
    remaining_profit_percent = (
        ((current_price - avg_buy_price) / avg_buy_price) * 100
        if avg_buy_price > 0
        else 0.0
    )
    open_date_value = open_trade.get("open_date") if open_trade else None

    closed_trade_payload: dict[str, Any] | None = None
    if snapshot.partial_amount > 0 and open_timestamp_ms is not None:
        close_date = closed_at or datetime.now()
        close_timestamp = close_date.timestamp() * 1000
        open_date = datetime.fromtimestamp(open_timestamp_ms / 1000.0)
        duration_data = calculate_trade_duration(open_timestamp_ms, close_timestamp)
        partial_avg_sell_price = snapshot.partial_proceeds / snapshot.partial_amount
        partial_profit = snapshot.partial_proceeds - sold_cost
        partial_profit_percent = (
            ((partial_avg_sell_price - avg_buy_price) / avg_buy_price) * 100
            if avg_buy_price > 0
            else 0.0
        )
        closed_trade_payload = {
            "symbol": snapshot.symbol,
            "deal_id": deal_id or None,
            "execution_history_complete": execution_history_complete,
            "so_count": so_count,
            "profit": partial_profit,
            "profit_percent": partial_profit_percent,
            "amount": snapshot.partial_amount,
            "cost": sold_cost,
            "tp_price": partial_avg_sell_price,
            "avg_price": avg_buy_price,
            "open_date": open_date,
            "close_date": close_date,
            "duration": duration_data,
        }

    unsellable_payload = {
        "symbol": snapshot.symbol,
        "deal_id": deal_id or None,
        "execution_history_complete": execution_history_complete,
        "so_count": so_count,
        "profit": remaining_profit,
        "profit_percent": remaining_profit_percent,
        "amount": snapshot.remaining_amount,
        "cost": remaining_cost,
        "current_price": current_price,
        "avg_price": (
            (remaining_cost / snapshot.remaining_amount)
            if snapshot.remaining_amount > 0
            else 0.0
        ),
        "open_date": str(open_date_value) if open_date_value is not None else None,
        "unsellable_reason": snapshot.reason,
        "unsellable_min_notional": snapshot.min_notional,
        "unsellable_estimated_notional": snapshot.estimated_notional,
        "unsellable_since": unsellable_since or datetime.now().isoformat(),
    }
    monitor_payload = {
        "symbol": snapshot.symbol,
        "side": "sell",
        "reason": snapshot.reason,
        "partial_filled_amount": snapshot.partial_amount,
        "partial_proceeds": snapshot.partial_proceeds,
        "remaining_amount": snapshot.remaining_amount,
        "unsellable_min_notional": snapshot.min_notional,
        "unsellable_estimated_notional": snapshot.estimated_notional,
    }
    return UnsellableRemainderContext(
        symbol=snapshot.symbol,
        partial_amount=snapshot.partial_amount,
        partial_proceeds=snapshot.partial_proceeds,
        remaining_amount=snapshot.remaining_amount,
        reason=snapshot.reason,
        min_notional=snapshot.min_notional,
        estimated_notional=snapshot.estimated_notional,
        already_notified=already_notified,
        closed_trade_payload=closed_trade_payload,
        unsellable_payload=unsellable_payload,
        monitor_payload=monitor_payload,
    )
