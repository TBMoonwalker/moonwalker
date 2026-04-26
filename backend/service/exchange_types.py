"""Typed payload contracts for exchange order flows."""

from typing import Any, TypedDict


class ExchangeOrderPayload(TypedDict, total=False):
    """Mutable order payload shared across exchange execution paths."""

    id: str
    symbol: str
    ordertype: str
    side: str
    amount: float | str
    total_amount: float
    total_cost: float
    actual_pnl: float
    ordersize: float
    price: float | str
    limit_price: float | str
    current_price: float | str
    cost: float
    timestamp: int
    fee: Any
    orderid: str
    botname: str
    amount_fee: float
    base_fee: float
    fees: float
    precision: int
    baseorder: bool
    safetyorder: bool
    order_count: int
    so_percentage: float | None
    direction: str
    signal_name: str | None
    strategy_name: str | None
    timeframe: str | None
    metadata_json: str | None
    baseline_order_size: float
    entry_size_applied: bool
    entry_size_reason_code: str | None
    entry_size_fallback_applied: bool
    entry_size_fallback_reason: str | None
    type: str
    fallback_min_price: float | str | None
    requires_market_fallback: bool
    limit_cancel_confirmed: bool
    remaining_amount: float
    partial_filled_amount: float
    partial_avg_price: float
    _limit_cancel_confirmed: bool
    _sell_retry_count: int


class ParsedOrderStatus(TypedDict, total=False):
    """Normalized order status used after exchange trade reconciliation."""

    timestamp: int
    amount: float
    total_amount: float
    price: float | str
    orderid: str
    symbol: str
    side: str
    amount_fee: Any
    base_fee: float
    ordersize: float


class TradeExecutionPayload(TypedDict, total=False):
    """Serializable execution metadata attached to sell status payloads."""

    symbol: str
    side: str
    role: str
    timestamp: str | int
    price: float
    amount: float
    ordersize: float
    fee: float
    order_id: str | None
    order_type: str | None
    order_count: int | None
    so_percentage: float | None
    signal_name: str | None
    strategy_name: str | None
    timeframe: str | None
    metadata_json: str | None


class PartialSellStatus(TypedDict, total=False):
    """Partial or unsellable sell status result."""

    type: str
    symbol: str
    partial_filled_amount: float
    partial_avg_price: float
    partial_proceeds: float
    remaining_amount: float
    unsellable: bool
    unsellable_reason: str | None
    unsellable_min_notional: float | None
    unsellable_estimated_notional: float | None
    executions: list[TradeExecutionPayload]


class MarketFallbackStatus(TypedDict, total=False):
    """Status payload that instructs the caller to use market fallback."""

    requires_market_fallback: bool
    limit_cancel_confirmed: bool
    fallback_reason: str
    symbol: str
    remaining_amount: float
    partial_filled_amount: float
    partial_avg_price: float
    executions: list[TradeExecutionPayload]


class SoldCheckStatus(TypedDict, total=False):
    """Normalized completed sell payload for close processing."""

    type: str
    sell: bool
    total_cost: float
    actual_pnl: Any
    total_amount: float
    price: float
    symbol: str
    avg_price: float
    tp_price: float
    profit: float
    profit_percent: float
    timestamp: int
    orderid: str
    side: str
    amount_fee: Any
    base_fee: float
    ordersize: float
    executions: list[TradeExecutionPayload]
