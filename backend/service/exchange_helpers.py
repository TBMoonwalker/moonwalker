"""Utility helpers for exchange order and balance handling."""

from decimal import Decimal, localcontext
from typing import Any

from service.exchange_types import ExchangeOrderReport
from service.feedback_accounting import execution_accounting


def is_matching_order_id(candidate_order_id: Any, expected_order_id: str) -> bool:
    """Compare order ids safely across string/int exchange payloads."""
    if candidate_order_id is None:
        return False
    return str(candidate_order_id) == str(expected_order_id)


def aggregate_matched_trades(
    matched_orders: list[dict[str, Any]],
    symbol: str,
) -> dict[str, Any]:
    """Aggregate partial fills into one trade-like payload."""
    if not matched_orders or len(matched_orders) > 1000:
        raise ValueError("A bounded, nonempty execution list is required.")
    last_order = max(matched_orders, key=lambda row: int(row.get("timestamp") or 0))
    order_id = str(last_order["order"])
    side = last_order["side"]
    seen: set[str] = set()
    reports = []
    with localcontext() as context:
        context.prec = 512
        for row in matched_orders:
            if (
                str(row.get("order")) != order_id
                or row.get("symbol", symbol) != symbol
                or row.get("side") != side
            ):
                raise ValueError("Execution evidence belongs to another order.")
            identity = row.get("id")
            if (
                isinstance(identity, bool)
                or not isinstance(identity, (str, int))
                or not str(identity)
            ):
                raise ValueError("An execution identity is required.")
            if str(identity) in seen:
                raise ValueError("Duplicate execution identity.")
            seen.add(str(identity))
            report = ExchangeOrderReport.from_order(
                {
                    "id": order_id,
                    "symbol": symbol,
                    "side": side,
                    "filled": row["amount"],
                    "cost": row["cost"],
                    "timestamp": row["timestamp"],
                    "fees": row.get("fees"),
                    "fee": row.get("fee"),
                }
            )
            reports.append(report)
        amount = sum((Decimal(row.filled) for row in reports), Decimal(0))
        cost = sum((Decimal(row.quote_cost) for row in reports), Decimal(0))
        fees: dict[str, Decimal] = {}
        for row in reports:
            for currency, value in row.fees.items():
                fees[currency] = fees.get(currency, Decimal(0)) + Decimal(value)
        combined = ExchangeOrderReport(
            order_id,
            symbol,
            side,
            format(amount, "f"),
            format(cost, "f"),
            {key: format(value, "f") for key, value in fees.items()},
            all(row.fees_complete for row in reports),
            False,
            int(last_order["timestamp"]),
        )
        base_fee = (
            fees.get(symbol.split("/")[0].upper(), Decimal(0))
            if side == "buy"
            else Decimal(0)
        )
        # Unitless fee totals remain only in the legacy output, never the report.
        legacy_fee = float(sum(fees.values(), Decimal(0)))
        return {
            "cost": float(cost),
            "fee": legacy_fee,
            "fee_cost": legacy_fee,
            "base_fee": float(base_fee),
            "amount": float(amount),
            "timestamp": combined.timestamp_ms,
            "price": float(cost / amount) if amount else last_order["price"],
            "order": order_id,
            "symbol": symbol,
            "side": side,
            "execution_report": combined,
            "feedback_accounting": execution_accounting(matched_orders, symbol),
        }


def precision_step_for_amount(amount_str: str) -> float:
    """Infer amount step from a precision-formatted string."""
    if "." not in amount_str:
        return 1.0

    decimals = amount_str.split(".", 1)[1]
    decimals = decimals.rstrip("0")
    if not decimals:
        return 1.0
    return 10 ** (-len(decimals))


def safe_float(value: Any) -> float | None:
    """Convert a value to float when possible."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_free_amount(balance: dict[str, Any], asset: str) -> float | None:
    """Extract free amount for an asset from a CCXT balance payload."""
    free_amount = None
    asset_info = balance.get(asset)
    if isinstance(asset_info, dict):
        free_amount = asset_info.get("free")

    if free_amount is None:
        free_map = balance.get("free")
        if isinstance(free_map, dict):
            free_amount = free_map.get(asset)

    if free_amount is None:
        return None

    try:
        return float(free_amount)
    except (TypeError, ValueError):
        return None
