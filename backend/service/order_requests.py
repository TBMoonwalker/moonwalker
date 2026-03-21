"""Parsing and validation helpers for incoming order requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from service.trade_math import count_decimal_places, parse_date_to_ms


@dataclass(frozen=True)
class ManualBuyAddRequest:
    """Validated manual buy-add request payload."""

    symbol: str
    timestamp_ms: int
    price: float
    amount: float
    amount_precision: int


def normalize_order_symbol(symbol: str) -> str:
    """Normalize symbol input into BASE/QUOTE format."""
    normalized = str(symbol or "").strip().upper().replace(" ", "")
    normalized = normalized.replace("_", "/")
    if "-" in normalized and "/" not in normalized:
        normalized = normalized.replace("-", "/")

    parts = normalized.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Invalid symbol. Use BASE/QUOTE format.")
    return f"{parts[0]}/{parts[1]}"


def parse_positive_float(value: Any, field_name: str) -> float:
    """Parse and validate positive numeric payload fields."""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field_name}.") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than 0.")
    return parsed


def parse_manual_buy_add_request(
    symbol: str,
    date_input: Any,
    price_raw: Any,
    amount_raw: Any,
) -> ManualBuyAddRequest:
    """Validate and normalize a manual buy-add request."""
    normalized_symbol = normalize_order_symbol(symbol)
    price = parse_positive_float(price_raw, "price")
    amount = parse_positive_float(amount_raw, "amount")
    timestamp_ms = parse_date_to_ms(str(date_input or "").strip())
    if timestamp_ms is None:
        raise ValueError("Invalid date.")

    return ManualBuyAddRequest(
        symbol=normalized_symbol,
        timestamp_ms=int(timestamp_ms),
        price=float(price),
        amount=float(amount),
        amount_precision=count_decimal_places(str(amount_raw)),
    )
