"""Utility helpers for exchange order and balance handling."""

from typing import Any


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
    amount = 0.0
    fee = 0.0
    cost = 0.0
    base_fee = 0.0

    for order in matched_orders:
        amount += float(order["amount"])
        fee_data = order.get("fee") or {}
        fee_cost = float(fee_data.get("cost") or 0.0)
        fee += fee_cost
        cost += float(order["cost"])
        fee_currency = str(fee_data.get("currency") or "").upper()
        base_asset = str(order.get("symbol", symbol)).split("/")[0].upper()
        side = str(order.get("side") or "").lower()
        if side == "buy" and fee_currency == base_asset:
            base_fee += fee_cost

    last_order = max(matched_orders, key=lambda o: int(o.get("timestamp") or 0))

    trade: dict[str, Any] = {}
    trade["cost"] = cost
    trade["fee"] = fee
    trade["base_fee"] = base_fee
    trade["amount"] = amount
    trade["timestamp"] = last_order["timestamp"]
    trade["price"] = (cost / amount) if amount > 0 else last_order["price"]
    trade["order"] = last_order["order"]
    trade["symbol"] = last_order["symbol"]
    trade["side"] = last_order["side"]
    trade["fee_cost"] = fee

    return trade


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
