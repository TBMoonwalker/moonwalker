"""Helpers for shaping sell execution results."""

from typing import Any

from service.exchange_types import (
    PartialSellStatus,
    SoldCheckStatus,
    TradeExecutionPayload,
)


def _optional_float(value: Any) -> float | None:
    """Return a float for a present value, otherwise ``None``."""
    if value is None:
        return None
    return float(value)


def _build_sell_execution_from_status(
    order_status: dict[str, Any],
    *,
    symbol: str,
    role: str,
    amount_field: str,
    fallback_price: float = 0.0,
) -> TradeExecutionPayload | None:
    """Build one execution row from a normalized sell status payload."""
    amount = float(order_status.get(amount_field) or 0.0)
    if amount <= 0:
        return None

    fee = _optional_float(order_status.get("base_fee"))
    if fee is None:
        fee = _optional_float(order_status.get("fee"))

    timestamp = order_status.get("timestamp")
    return {
        "symbol": str(order_status.get("symbol") or symbol),
        "side": str(order_status.get("side") or "sell"),
        "role": role,
        "timestamp": str(int(timestamp)) if timestamp is not None else "",
        "price": float(order_status.get("price") or fallback_price or 0.0),
        "amount": amount,
        "ordersize": float(order_status.get("ordersize") or amount * fallback_price),
        "fee": float(fee or 0.0),
        "order_id": (
            str(order_status.get("orderid"))
            if order_status.get("orderid") is not None
            else None
        ),
        "order_type": (
            str(order_status.get("ordertype"))
            if order_status.get("ordertype") is not None
            else None
        ),
    }


def build_partial_sell_status(
    *,
    symbol: str,
    partial_amount: float,
    partial_avg_price: float,
    remaining_amount: float,
    executions: list[TradeExecutionPayload] | None = None,
    unsellable: bool = False,
    unsellable_reason: str | None = None,
    unsellable_min_notional: float | None = None,
    unsellable_estimated_notional: float | None = None,
) -> PartialSellStatus:
    """Build a partial execution status for deferred close accounting."""
    return {
        "type": "partial_sell",
        "symbol": symbol,
        "partial_filled_amount": float(partial_amount),
        "partial_avg_price": float(partial_avg_price),
        "partial_proceeds": float(partial_amount * partial_avg_price),
        "remaining_amount": float(remaining_amount),
        "unsellable": bool(unsellable),
        "unsellable_reason": unsellable_reason,
        "unsellable_min_notional": _optional_float(unsellable_min_notional),
        "unsellable_estimated_notional": _optional_float(unsellable_estimated_notional),
        **({"executions": list(executions)} if executions else {}),
    }


def finalize_sell_order_status(
    order_status: dict[str, Any],
    *,
    total_cost: float,
    actual_pnl: Any,
) -> SoldCheckStatus:
    """Enrich a normalized sell order status with close metrics."""
    normalized: SoldCheckStatus = dict(order_status)
    normalized["type"] = "sold_check"
    normalized["sell"] = True
    normalized["total_cost"] = total_cost
    normalized["actual_pnl"] = actual_pnl

    total_amount = float(normalized["total_amount"])
    price = float(normalized["price"])
    avg_buy_price = total_cost / total_amount
    profit = (price * total_amount) - total_cost
    profit_percent = ((price - avg_buy_price) / avg_buy_price) * 100

    normalized["avg_price"] = avg_buy_price
    normalized["tp_price"] = price
    normalized["profit"] = profit
    normalized["profit_percent"] = profit_percent
    if not normalized.get("executions"):
        execution = _build_sell_execution_from_status(
            normalized,
            symbol=str(normalized["symbol"]),
            role="final_sell",
            amount_field="total_amount",
            fallback_price=price,
        )
        normalized["executions"] = [execution] if execution else []
    return normalized


def combine_partial_sell_statuses(
    *,
    symbol: str,
    first_partial_amount: float,
    first_partial_price: float,
    second_status: PartialSellStatus,
    first_partial_executions: list[TradeExecutionPayload] | None = None,
) -> PartialSellStatus:
    """Combine two partial sell execution results into one partial status."""
    second_partial_amount = float(second_status.get("partial_filled_amount") or 0.0)
    second_partial_price = float(second_status.get("partial_avg_price") or 0.0)
    combined_partial_amount = first_partial_amount + second_partial_amount
    combined_proceeds = (
        first_partial_amount * first_partial_price
        + second_partial_amount * second_partial_price
    )
    combined_partial_price = (
        combined_proceeds / combined_partial_amount
        if combined_partial_amount > 0
        else 0.0
    )
    return build_partial_sell_status(
        symbol=symbol,
        partial_amount=combined_partial_amount,
        partial_avg_price=combined_partial_price,
        remaining_amount=float(second_status.get("remaining_amount") or 0.0),
        executions=[
            *(first_partial_executions or []),
            *list(second_status.get("executions") or []),
        ],
        unsellable=bool(second_status.get("unsellable", False)),
        unsellable_reason=(
            str(second_status.get("unsellable_reason"))
            if second_status.get("unsellable_reason")
            else None
        ),
        unsellable_min_notional=_optional_float(
            second_status.get("unsellable_min_notional")
        ),
        unsellable_estimated_notional=_optional_float(
            second_status.get("unsellable_estimated_notional")
        ),
    )


def merge_partial_fill_with_market_sell(
    market_status: SoldCheckStatus,
    *,
    partial_amount: float,
    partial_price: float,
    total_cost: float,
    partial_executions: list[TradeExecutionPayload] | None = None,
) -> SoldCheckStatus:
    """Merge a partial limit fill with a completed market fallback sell."""
    merged: SoldCheckStatus = dict(market_status)
    market_amount = float(merged.get("total_amount") or 0.0)
    market_price = float(merged.get("price") or 0.0)
    combined_amount = partial_amount + market_amount
    if combined_amount <= 0:
        return merged

    proceeds = (partial_amount * partial_price) + (market_amount * market_price)
    avg_sell_price = proceeds / combined_amount
    avg_buy_price = total_cost / combined_amount if combined_amount > 0 else 0.0
    profit = proceeds - total_cost
    profit_percent = (
        ((avg_sell_price - avg_buy_price) / avg_buy_price) * 100
        if avg_buy_price > 0
        else 0.0
    )

    merged["total_amount"] = combined_amount
    merged["price"] = avg_sell_price
    merged["tp_price"] = avg_sell_price
    merged["avg_price"] = avg_buy_price
    merged["profit"] = profit
    merged["profit_percent"] = profit_percent
    merged["executions"] = [
        *(partial_executions or []),
        *list(merged.get("executions") or []),
    ]
    return merged
