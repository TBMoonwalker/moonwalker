"""Helpers for exchange trade lookup and order-status normalization."""

from typing import Any, Protocol

import ccxt.async_support as ccxt
from service.exchange_helpers import aggregate_matched_trades, is_matching_order_id
from service.exchange_types import ExchangeOrderPayload, ParsedOrderStatus


class LoggerLike(Protocol):
    """Logger interface used by exchange lookup helpers."""

    def debug(self, msg: str, *args: object) -> None:
        """Log debug exchange lookup details."""


async def fetch_matching_order_trades(
    exchange: Any,
    symbol: str,
    orderid: str,
    since: int,
) -> list[dict[str, Any]]:
    """Fetch account trades and filter them down to one order id."""
    try:
        orderlist = await exchange.fetch_my_trades(symbol, since, 1000)
    except TypeError:
        orderlist = await exchange.fetch_my_trades(symbol, since)
    return [
        order
        for order in (orderlist or [])
        if is_matching_order_id(order.get("order"), orderid)
    ]


async def lookup_aggregated_trade(
    exchange: Any,
    *,
    logger: LoggerLike,
    symbol: str,
    orderid: str,
    order_check_range_seconds: int,
    order_timestamp: int | None = None,
) -> dict[str, Any] | None:
    """Resolve an order id to one aggregated trade-like payload."""
    since = exchange.milliseconds() - (order_check_range_seconds * 1000)
    if order_timestamp:
        since = min(int(order_timestamp) - 1000, since)

    matched_orders: list[dict[str, Any]] = []
    try:
        fetched = await exchange.fetch_order_trades(orderid, symbol)
        matched_orders = [
            order
            for order in (fetched or [])
            if is_matching_order_id(order.get("order"), orderid)
        ]
    except (ccxt.BaseError, TypeError, ValueError):
        matched_orders = []

    if not matched_orders:
        matched_orders = await fetch_matching_order_trades(
            exchange,
            symbol,
            orderid,
            since,
        )
    if not matched_orders and order_timestamp:
        matched_orders = await fetch_matching_order_trades(
            exchange,
            symbol,
            orderid,
            int(order_timestamp) - 86_400_000,
        )

    if not matched_orders:
        return None

    logger.debug(
        "Orderlist for %s with orderid: %s: %s",
        symbol,
        orderid,
        matched_orders,
    )
    return aggregate_matched_trades(matched_orders, symbol)


def build_parsed_order_status(
    order: ExchangeOrderPayload,
    trade: dict[str, Any] | None,
) -> ParsedOrderStatus:
    """Normalize reconciled or fallback order data for downstream processing."""
    data: ParsedOrderStatus = {
        "timestamp": 0,
        "amount": 0.0,
        "total_amount": 0.0,
        "price": 0.0,
        "orderid": "",
        "symbol": "",
        "side": "",
        "amount_fee": 0.0,
        "base_fee": 0.0,
        "ordersize": 0.0,
    }

    if trade:
        data["timestamp"] = trade["timestamp"]
        data["amount"] = float(trade["amount"])
        data["total_amount"] = float(trade["amount"])
        data["price"] = trade["price"]
        data["orderid"] = trade["order"]
        data["symbol"] = trade["symbol"]
        data["side"] = trade["side"]
        data["amount_fee"] = trade["fee_cost"]
        data["base_fee"] = float(trade.get("base_fee") or 0.0)
        data["ordersize"] = order["cost"]
        return data

    data["timestamp"] = order["timestamp"]
    data["amount"] = float(order["amount"])
    data["total_amount"] = float(order["amount"])
    data["price"] = order["price"]
    data["orderid"] = order["id"]
    data["symbol"] = order["symbol"]
    data["side"] = order["side"]
    data["amount_fee"] = order["fee"]
    data["base_fee"] = 0.0
    data["ordersize"] = order["cost"]
    return data
