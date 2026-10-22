"""Complete missing fees only from bounded, authenticated executions of one order."""

import asyncio
from decimal import Decimal, localcontext
from typing import Any

import ccxt.async_support as ccxt
from service.accumulation_fill import AccumulationFill, decimal_evidence


async def hydrate_accumulation_order(
    exchange: Any, order: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    """Keep incomplete evidence unchanged when execution coverage cannot be proved."""
    report = AccumulationFill.from_order(order)
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
