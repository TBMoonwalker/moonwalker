"""Shared trading math helpers for manual buy and CSV import flows."""

from __future__ import annotations

from datetime import datetime

DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
)


def calculate_order_size(price: float, amount: float) -> float:
    """Calculate order size in quote currency."""
    return float(price) * float(amount)


def calculate_so_percentage(
    price: float,
    previous_price: float | None,
    *,
    is_base: bool = False,
) -> float:
    """Calculate signed percentage change versus previous order price."""
    if is_base or previous_price is None or previous_price <= 0:
        return 0.0
    return round(((price - previous_price) / previous_price) * 100, 2)


def parse_date_to_ms(value: str) -> int | None:
    """Parse date-like values to Unix milliseconds."""
    normalized_value = value.strip()
    if not normalized_value:
        return None

    if normalized_value.isdigit():
        numeric = int(normalized_value)
        if numeric > 10_000_000_000:
            return numeric
        return numeric * 1000

    iso_value = normalized_value.replace("Z", "+00:00")
    try:
        iso_dt = datetime.fromisoformat(iso_value)
        return int(iso_dt.timestamp() * 1000)
    except ValueError:
        pass

    for date_format in DATE_FORMATS:
        try:
            parsed = datetime.strptime(normalized_value, date_format)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            continue

    return None


def count_decimal_places(value: str) -> int:
    """Count decimal places for a numeric string."""
    if "." not in value:
        return 0
    return len(value.split(".", maxsplit=1)[1].rstrip("0"))
