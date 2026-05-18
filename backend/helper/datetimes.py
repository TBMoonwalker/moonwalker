"""Datetime and duration parsing helpers for closed-trade analytics."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_DurationPattern = re.compile(
    r"^(?:(?P<days>\d+)\s+days?,\s*)?"
    r"(?P<hours>\d+):(?P<minutes>\d{2}):(?P<seconds>\d{2})"
    r"(?:\.(?P<microseconds>\d+))?$"
)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_datetime(value: Any) -> datetime | None:
    """Best-effort parsing for the mixed date formats used in closed trades."""
    if isinstance(value, datetime):
        return ensure_utc(value)

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1_000_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None

    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None

    if normalized.isdigit():
        return parse_datetime(int(normalized))

    for candidate in (
        normalized.replace("Z", "+00:00"),
        normalized,
    ):
        try:
            return ensure_utc(datetime.fromisoformat(candidate))
        except ValueError:
            continue

    for pattern in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return ensure_utc(datetime.strptime(normalized, pattern))
        except ValueError:
            continue

    return None


def parse_duration_hours(
    value: Any,
    *,
    open_date: Any = None,
    close_date: Any = None,
) -> float | None:
    """Return duration in hours using the best available source.

    Tries open_date/close_date first for accurate results, falls back to
    parsing the value field (numeric or timedeltas string).
    """
    opened_at = parse_datetime(open_date) if open_date is not None else None
    closed_at = parse_datetime(close_date) if close_date is not None else None
    if opened_at and closed_at and closed_at >= opened_at:
        return max((closed_at - opened_at).total_seconds() / 3600, 0.0)

    if value is None:
        return None

    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric >= 3600:
            return numeric / 3600
        if numeric >= 60:
            return numeric / 60
        return numeric

    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None

    try:
        return parse_duration_hours(float(normalized))
    except ValueError:
        pass

    matched = _DurationPattern.match(normalized)
    if matched:
        days = int(matched.group("days") or 0)
        hours = int(matched.group("hours") or 0)
        minutes = int(matched.group("minutes") or 0)
        seconds = int(matched.group("seconds") or 0)
        microseconds = int((matched.group("microseconds") or "0")[:6].ljust(6, "0"))
        total_seconds = (
            days * 86_400
            + hours * 3_600
            + minutes * 60
            + seconds
            + microseconds / 1_000_000
        )
        return total_seconds / 3600

    return None
