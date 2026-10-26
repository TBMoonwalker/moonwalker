"""Typed payload contracts for exchange order flows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, NotRequired, Self, TypedDict

from service.order_requests import normalize_order_symbol


class ExchangeOrderPayload(TypedDict, total=False):
    """Mutable order payload shared across exchange execution paths."""

    id: str
    operation_id: str
    source_operation_id: str
    client_order_id: str
    symbol: str
    ordertype: str
    side: str
    campaign_id: str | None
    amount: float | str
    total_amount: float
    requested_total_amount: float
    total_cost: float
    actual_pnl: float
    ordersize: float
    price: float | str
    maximum_buy_price: float | str | None
    limit_price: float | str
    current_price: float | str
    cost: float
    filled: float
    remaining: float
    average: float
    status: str
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
    strategy_slug: str | None
    strategy_version: int | None
    timeframe: str | None
    metadata_json: str | None
    close_reason: str | None
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
    _execution_scope: str
    _placement_operation_id: str
    _placement_source_operation_id: str
    _placement_operation_ids: list[str]


class ExecutionFill(TypedDict):
    """Required normalized fill that leaves the exchange adapter."""

    timestamp: int
    amount: float
    total_amount: float
    price: float | str
    orderid: str
    symbol: str
    side: str
    metadata_json: NotRequired[str]
    amount_fee: NotRequired[Any]
    base_fee: NotRequired[float]
    ordersize: NotRequired[float]


ParsedOrderStatus = ExecutionFill


class TradeExecutionPayload(TypedDict, total=False):
    """Serializable execution metadata attached to sell status payloads."""

    symbol: str
    side: str
    role: str
    campaign_id: str | None
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
    strategy_slug: str | None
    strategy_version: int | None
    timeframe: str | None
    metadata_json: str | None


class PartialSellStatus(TypedDict, total=False):
    """Partial or unsellable sell status result."""

    type: str
    symbol: str
    campaign_id: str | None
    close_reason: str | None
    strategy_name: str | None
    strategy_slug: str | None
    strategy_version: int | None
    timeframe: str | None
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
    exchange_order_id: str
    remaining_amount: float
    partial_filled_amount: float
    partial_avg_price: float
    unsellable_min_notional: float | None
    unsellable_estimated_notional: float | None
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
    campaign_id: str | None
    timestamp: int
    orderid: str
    side: str
    close_reason: str | None
    strategy_name: str | None
    strategy_slug: str | None
    strategy_version: int | None
    timeframe: str | None
    amount_fee: Any
    base_fee: float
    ordersize: float
    metadata_json: str | None
    executions: list[TradeExecutionPayload]


def canonical_decimal(value: str, *, positive: bool = False) -> str:
    """Validate exact monetary strings without accepting binary float inputs."""
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError("Expected a bounded decimal string.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal string.") from exc
    if not parsed.is_finite() or parsed < 0 or (positive and parsed == 0):
        raise ValueError("Decimal must be finite and nonnegative.")
    if abs(parsed.as_tuple().exponent) > 128:
        raise ValueError("Decimal exponent is out of bounds.")
    return format(parsed, "f") if parsed else "0"


TERMINAL_ORDER_STATUSES = frozenset(
    {"closed", "filled", "canceled", "cancelled", "expired", "rejected"}
)


def decimal_evidence(value: Any) -> str:
    """Preserve a reported number's decimal spelling; reject absent/invalid data."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Missing or invalid decimal evidence.")
    return canonical_decimal(str(value))


@dataclass(frozen=True)
class ExchangeOrderReport:
    """Validated cumulative order report from a trusted exchange lookup adapter."""

    order_id: str
    symbol: str
    side: str
    filled: str
    quote_cost: str
    fees: dict[str, str]
    fees_complete: bool
    terminal: bool
    timestamp_ms: int
    requested_quantity: str | None = None
    order_status: str | None = None

    @classmethod
    def from_order(cls, order: dict[str, Any]) -> Self:
        """Read raw CCXT order totals without guessing missing fees or cost."""
        if not isinstance(order, dict):
            raise ValueError("An order evidence object is required.")
        order_id = order.get("id")
        if not isinstance(order_id, str) or not order_id or len(order_id) > 128:
            raise ValueError("An exchange order identity is required.")
        symbol = order.get("symbol")
        if not isinstance(symbol, str) or len(symbol.split("/")) != 2 or ":" in symbol:
            raise ValueError("A spot symbol is required.")
        side = order.get("side")
        if not isinstance(side, str) or side not in {"buy", "sell"}:
            raise ValueError("An explicit fill side is required.")
        status = order.get("status")
        if status is not None and (
            not isinstance(status, str)
            or status not in TERMINAL_ORDER_STATUSES | {"open"}
        ):
            raise ValueError("Unknown order status is not fill evidence.")
        filled, cost = (
            decimal_evidence(order.get("filled")),
            decimal_evidence(order.get("cost")),
        )
        if (Decimal(filled) > 0) != (Decimal(cost) > 0):
            raise ValueError("Filled quantity and cost must agree.")
        if status in {"closed", "filled"} and Decimal(filled) == 0:
            raise ValueError("A closed order needs positive fill evidence.")
        timestamp = order.get("lastTradeTimestamp") or order.get("timestamp")
        if type(timestamp) is not int or not 0 <= timestamp < 2**63:
            raise ValueError("A valid execution timestamp is required.")
        raw_fees = order.get("fees")
        if not raw_fees:
            raw_fees = [order["fee"]] if order.get("fee") else []
        if not isinstance(raw_fees, list) or len(raw_fees) > 32:
            raise ValueError("Invalid or oversized fee evidence.")
        fees: dict[str, str] = {}
        with localcontext() as context:
            context.prec = 512
            for fee in raw_fees:
                if not isinstance(fee, dict):
                    raise ValueError("Invalid fee evidence.")
                currency = fee.get("currency")
                value = Decimal(decimal_evidence(fee.get("cost")))
                if value == 0 and currency in (None, ""):
                    continue
                if not isinstance(currency, str) or not currency or len(currency) > 32:
                    raise ValueError("Fee currency is required.")
                currency = currency.upper()
                fees[currency] = format(Decimal(fees.get(currency, "0")) + value, "f")
        if Decimal(filled) == 0 and any(Decimal(value) for value in fees.values()):
            raise ValueError("Zero-fill fees require explicit repair.")
        return cls(
            order_id,
            normalize_order_symbol(symbol),
            side,
            filled,
            cost,
            fees,
            bool(raw_fees) or Decimal(filled) == 0,
            status in TERMINAL_ORDER_STATUSES,
            timestamp,
            requested_quantity=(
                decimal_evidence(order["amount"])
                if order.get("amount") is not None
                else None
            ),
            order_status=status,
        )

    def serialize(self) -> str:
        """Return a stable checkpoint representation."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
