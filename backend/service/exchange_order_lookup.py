"""Helpers for exchange trade lookup and order-status normalization."""

import asyncio
import json
from decimal import Decimal, localcontext
from typing import Any, Protocol

import ccxt.async_support as ccxt
from service.exchange_helpers import aggregate_matched_trades, is_matching_order_id
from service.exchange_types import (
    ExchangeOrderPayload,
    ExchangeOrderReport,
    ParsedOrderStatus,
    decimal_evidence,
)
from service.feedback_accounting import (
    execution_accounting,
)


class LoggerLike(Protocol):
    """Logger interface used by exchange lookup helpers."""

    def debug(self, msg: str, *args: object) -> None:
        """Log debug exchange lookup details."""
        del msg  # Retain the standard logging keyword in this protocol signature.


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
        "Private fill lookup symbol=%s order_id=%s matched_count=%s",
        symbol,
        orderid,
        len(matched_orders),
    )
    return aggregate_matched_trades(matched_orders, symbol)


def build_parsed_order_status(
    order: ExchangeOrderPayload,
    trade: dict[str, Any] | None,
) -> ParsedOrderStatus:
    """Normalize reconciled or fallback order data for downstream processing."""
    report: ExchangeOrderReport | None = None
    accounting = (trade or {}).get("feedback_accounting")
    if trade:
        candidate = trade.get("execution_report")
        if isinstance(candidate, ExchangeOrderReport):
            report = candidate
        else:
            # Legacy aggregate fixtures/results carry actual execution quantity.
            report = ExchangeOrderReport.from_order(
                {
                    "id": str(trade["order"]),
                    "symbol": trade["symbol"],
                    "side": trade["side"],
                    "filled": trade["amount"],
                    "cost": trade.get("cost") or order.get("cost"),
                    "timestamp": trade["timestamp"],
                    "fees": trade.get("fees"),
                    "fee": trade.get("fee"),
                    "amount": order.get("amount"),
                    "status": order.get("status"),
                }
            )
    else:
        try:
            report = ExchangeOrderReport.from_order(dict(order))
        except ValueError:
            # An acknowledgement alone cannot establish a positive fill. The
            # owning lifecycle retains its raw evidence for authenticated lookup.
            report = None
    if accounting is None:
        accounting = execution_accounting([dict(order)], order["symbol"])
    metadata = {"feedback_accounting": accounting}
    if report is not None:
        metadata["execution_report"] = json.loads(report.serialize())
    else:
        accounting["complete"] = False
    amount = float(report.filled) if report else 0.0
    cost = float(report.quote_cost) if report else 0.0
    with localcontext() as context:
        context.prec = 512
        price = (
            str(Decimal(report.quote_cost) / Decimal(report.filled))
            if report and Decimal(report.filled) > 0
            else (trade or {}).get("price") or order.get("price") or 0.0
        )
    base = order["symbol"].split("/")[0].upper()
    return {
        "timestamp": report.timestamp_ms
        if report
        else int(order.get("timestamp") or 0),
        "amount": amount,
        "total_amount": amount,
        "price": price,
        "orderid": report.order_id if report else order["id"],
        "symbol": report.symbol if report else order["symbol"],
        "side": report.side if report else order["side"],
        "amount_fee": (
            float(sum((Decimal(value) for value in report.fees.values()), Decimal(0)))
            if report
            else 0.0
        ),
        "base_fee": (
            float(report.fees.get(base, "0"))
            if report and report.side == "buy"
            else float((trade or {}).get("base_fee") or 0.0)
        ),
        "ordersize": cost,
        "metadata_json": json.dumps(metadata, sort_keys=True),
    }


async def hydrate_spot_order_fees(
    exchange: Any, order: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    """Keep incomplete evidence unchanged when execution coverage cannot be proved."""
    report = ExchangeOrderReport.from_order(order)
    if report.fees_complete or report.filled == "0":
        return order
    reader = getattr(exchange, "read_spot_order_executions", None)
    if not callable(reader):
        return order
    try:
        async with asyncio.timeout(10):
            trades = await reader(order, config)
        if not isinstance(trades, list) or not 1 <= len(trades) <= 1000:
            return order
        seen: set[str] = set()
        fees: dict[str, Decimal] = {}
        with localcontext() as context:
            context.prec = 512
            quantity = Decimal(0)
            for trade in trades:
                if not isinstance(trade, dict):
                    return order
                identity = trade.get("id")
                if (
                    not isinstance(identity, str)
                    or not identity
                    or identity in seen
                    or trade.get("order") != report.order_id
                    or trade.get("symbol") != report.symbol
                    or trade.get("side") != report.side
                ):
                    return order
                seen.add(identity)
                amount = Decimal(decimal_evidence(trade.get("amount")))
                if amount <= 0:
                    return order
                quantity += amount
                raw = trade.get("fees") or (
                    [trade["fee"]] if trade.get("fee") else None
                )
                if not isinstance(raw, list) or not 1 <= len(raw) <= 32:
                    return order
                for fee in raw:
                    if not isinstance(fee, dict):
                        return order
                    currency = fee.get("currency")
                    if not isinstance(currency, str) or not 1 <= len(currency) <= 32:
                        return order
                    currency = currency.upper()
                    fees[currency] = fees.get(currency, Decimal(0)) + Decimal(
                        decimal_evidence(fee.get("cost"))
                    )
                    if len(fees) > 32:
                        return order
            if quantity != Decimal(report.filled):
                return order
            return {
                **order,
                "fees": [
                    {"currency": currency, "cost": format(cost, "f")}
                    for currency, cost in sorted(fees.items())
                ],
            }
    except (ValueError, TypeError, KeyError, ccxt.BaseError, OSError, TimeoutError):
        return order
