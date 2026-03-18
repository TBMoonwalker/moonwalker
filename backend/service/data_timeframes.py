"""Pure timeframe and history-window helpers for the data service."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


def timeframe_to_seconds(timerange: str) -> int:
    """Convert timeframe notation to seconds."""
    normalized = str(timerange or "").strip().lower()
    if not normalized:
        return 60

    normalized = normalized.replace("min", "m")
    match = re.fullmatch(r"(\d+)\s*([mhdw])", normalized)
    if not match:
        return 60

    value = int(match.group(1))
    unit = match.group(2)
    multipliers = {
        "m": 60,
        "h": 60 * 60,
        "d": 24 * 60 * 60,
        "w": 7 * 24 * 60 * 60,
    }
    return max(1, value) * multipliers[unit]


def timeframe_to_milliseconds(timerange: str) -> int:
    """Convert timeframe notation to milliseconds."""
    return timeframe_to_seconds(timerange) * 1000


def calculate_min_candle_date(
    *,
    timerange: str,
    length: int,
    lookback_buffer_multiplier: int,
    now: datetime | None = None,
) -> int:
    """Calculate the earliest timestamp in milliseconds for candle history."""
    timeframe_seconds = timeframe_to_seconds(timerange)
    candles = max(1, int(length))
    lookback_seconds = timeframe_seconds * candles * lookback_buffer_multiplier
    end_time = now or datetime.now(timezone.utc)
    min_date = end_time - timedelta(seconds=lookback_seconds)
    return int(min_date.timestamp() * 1000)


def resolve_required_history_window(
    *,
    history_data: int,
    timeframe: str,
    since_ms: int | None = None,
    now: datetime | None = None,
) -> tuple[int, int, int]:
    """Return normalized required history window and timeframe size."""
    timeframe_ms = max(1, timeframe_to_milliseconds(timeframe))
    now_dt = now or datetime.now(timezone.utc)
    now_ms = int(now_dt.timestamp() * 1000)
    current_candle_start = now_ms - (now_ms % timeframe_ms)
    required_until = max(0, current_candle_start - timeframe_ms)
    requested_since = (
        int(since_ms)
        if since_ms is not None
        else int((now_dt - timedelta(days=history_data)).timestamp() * 1000)
    )
    required_since = max(
        0,
        ((requested_since + timeframe_ms - 1) // timeframe_ms) * timeframe_ms,
    )
    if required_since > required_until:
        required_since = required_until
    return required_since, required_until, timeframe_ms
