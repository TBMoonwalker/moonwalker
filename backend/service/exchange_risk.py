"""Risk and precheck helpers for exchange order validation."""

from typing import Any

from service.exchange_helpers import safe_float


def get_min_notional_for_market(
    market: dict[str, Any] | None, *, is_market_order: bool
) -> float | None:
    """Resolve minimum notional from CCXT market metadata."""
    if not isinstance(market, dict):
        return None

    min_values: list[float] = []

    limits = market.get("limits")
    if isinstance(limits, dict):
        cost_limits = limits.get("cost")
        if isinstance(cost_limits, dict):
            min_cost = safe_float(cost_limits.get("min"))
            if min_cost and min_cost > 0:
                min_values.append(min_cost)

    info = market.get("info")
    if isinstance(info, dict):
        filters = info.get("filters")
        if isinstance(filters, list):
            for filter_data in filters:
                if not isinstance(filter_data, dict):
                    continue
                filter_type = str(filter_data.get("filterType", "")).upper()
                min_notional = safe_float(filter_data.get("minNotional"))
                if not min_notional or min_notional <= 0:
                    continue

                if filter_type == "MIN_NOTIONAL":
                    if (
                        is_market_order
                        and str(filter_data.get("applyToMarket", "true")).lower()
                        == "false"
                    ):
                        continue
                    min_values.append(min_notional)
                elif filter_type == "NOTIONAL":
                    if (
                        is_market_order
                        and str(filter_data.get("applyMinToMarket", "true")).lower()
                        == "false"
                    ):
                        continue
                    min_values.append(min_notional)

    if not min_values:
        return None
    return max(min_values)


def is_notional_below_minimum(
    amount: float,
    price: float,
    min_notional: float | None,
) -> tuple[bool, float | None, float]:
    """Check whether estimated notional is below the exchange minimum."""
    estimated_notional = max(0.0, float(amount)) * max(0.0, float(price))
    if min_notional is None:
        return False, None, estimated_notional
    return estimated_notional < min_notional, min_notional, estimated_notional


def resolve_required_buy_quote(order: dict[str, Any]) -> float | None:
    """Return required quote amount for a buy order."""
    requested_quote = safe_float(order.get("ordersize"))
    required_quote = (
        requested_quote if requested_quote and requested_quote > 0 else None
    )

    amount = safe_float(order.get("amount"))
    price = safe_float(order.get("price"))
    if amount is not None and amount > 0 and price is not None and price > 0:
        estimated_quote = amount * price
        if required_quote is None:
            required_quote = estimated_quote
        else:
            required_quote = max(required_quote, estimated_quote)

    if required_quote is None or required_quote <= 0:
        return None
    return float(required_quote)


def normalize_buy_buffer_pct(raw_value: Any) -> float:
    """Return a non-negative buy funds buffer percentage."""
    buffer_pct = safe_float(raw_value)
    if buffer_pct is None or buffer_pct < 0:
        return 0.0
    return float(buffer_pct)


def build_buy_precheck_result(
    *,
    ok: bool,
    reason: str,
    symbol: str,
    required_quote: float | None = None,
    available_quote: float | None = None,
    buffer_pct: float | None = None,
) -> dict[str, Any]:
    """Build a normalized buy precheck result payload."""
    result: dict[str, Any] = {
        "ok": ok,
        "reason": reason,
        "symbol": symbol,
    }
    if required_quote is not None:
        result["required_quote"] = round(float(required_quote), 8)
    if available_quote is not None:
        result["available_quote"] = round(float(available_quote), 8)
    else:
        result["available_quote"] = None
    if buffer_pct is not None:
        result["buffer_pct"] = round(float(buffer_pct), 6)
    return result
