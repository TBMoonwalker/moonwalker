"""Helpers for interpreting text-backed SQLite timestamps numerically."""

from __future__ import annotations

from typing import Any

from service.trade_math import parse_date_to_ms

NORMALIZED_TEXT_TIMESTAMP_SQL_TEMPLATE = (
    "CASE "
    "WHEN CAST({column} AS INTEGER) >= 100000000000 THEN CAST({column} AS INTEGER) "
    "WHEN CAST({column} AS INTEGER) >= 1000000000 THEN CAST({column} AS INTEGER) * 1000 "
    "ELSE CAST({column} AS INTEGER) "
    "END"
)


def build_normalized_text_timestamp_sql(column_name: str = "timestamp") -> str:
    """Return SQLite SQL that compares text timestamps as Unix milliseconds."""
    return NORMALIZED_TEXT_TIMESTAMP_SQL_TEMPLATE.format(column=column_name)


def coerce_timestamp_like_to_ms(value: Any) -> int | None:
    """Convert numeric or date-like values into Unix milliseconds."""
    if value is None:
        return None

    normalized_value = str(value).strip()
    if not normalized_value:
        return None

    if normalized_value.isdigit():
        numeric = int(normalized_value)
        if numeric >= 100_000_000_000:
            return numeric
        if numeric >= 1_000_000_000:
            return numeric * 1000
        return numeric

    return parse_date_to_ms(normalized_value)
