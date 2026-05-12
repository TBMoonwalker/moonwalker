"""Pure timeframe and history-window helpers for the data service."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_WEEKLY_BUCKET_ORIGIN = datetime(1970, 1, 5, tzinfo=timezone.utc)


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


def timeframe_bucket_origin_milliseconds(timerange: str) -> int:
    """Return the bucket origin in milliseconds for the timeframe."""
    normalized = str(timerange or "").strip().lower().replace("min", "m")
    match = re.fullmatch(r"(\d+)\s*([mhdw])", normalized)
    if not match:
        return 0

    if match.group(2) == "w":
        return int(_WEEKLY_BUCKET_ORIGIN.timestamp() * 1000)
    return 0


def align_timestamp_to_bucket_floor(
    timestamp_ms: int,
    timeframe_ms: int,
    origin_ms: int = 0,
) -> int:
    """Align a timestamp down to the active timeframe bucket boundary."""
    if timeframe_ms <= 0:
        return int(timestamp_ms)

    delta = int(timestamp_ms) - int(origin_ms)
    return ((delta // timeframe_ms) * timeframe_ms) + int(origin_ms)


def align_timestamp_to_bucket_ceil(
    timestamp_ms: int,
    timeframe_ms: int,
    origin_ms: int = 0,
) -> int:
    """Align a timestamp up to the next active timeframe bucket boundary."""
    if timeframe_ms <= 0:
        return int(timestamp_ms)

    delta = int(timestamp_ms) - int(origin_ms)
    return (((delta + timeframe_ms - 1) // timeframe_ms) * timeframe_ms) + int(
        origin_ms
    )


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
    origin_ms = timeframe_bucket_origin_milliseconds(timeframe)
    now_dt = now or datetime.now(timezone.utc)
    now_ms = int(now_dt.timestamp() * 1000)
    current_candle_start = align_timestamp_to_bucket_floor(
        now_ms,
        timeframe_ms,
        origin_ms,
    )
    required_until = max(0, current_candle_start - timeframe_ms)
    requested_since = (
        int(since_ms)
        if since_ms is not None
        else int((now_dt - timedelta(days=history_data)).timestamp() * 1000)
    )
    required_since = max(
        0,
        align_timestamp_to_bucket_ceil(
            requested_since,
            timeframe_ms,
            origin_ms,
        ),
    )
    if required_since > required_until:
        required_since = required_until
    return required_since, required_until, timeframe_ms
