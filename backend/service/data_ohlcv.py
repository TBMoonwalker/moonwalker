"""Pure OHLCV transformation helpers used by the data service."""

from __future__ import annotations

import os
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
from service.data_timeframes import timeframe_bucket_origin_milliseconds


def rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Create and sanitize a DataFrame from database rows."""
    df = pd.DataFrame(rows)
    df.dropna(inplace=True)
    return df


def append_live_candle(
    df_source: pd.DataFrame, live_candle: dict[str, float | str]
) -> pd.DataFrame:
    """Append in-memory live candle data to database candles."""
    return pd.concat([df_source, pd.DataFrame([live_candle])], ignore_index=True)


def build_resampled_ohlcv_payload(
    df_source: pd.DataFrame,
    timerange: str,
    offset: float,
) -> str | dict[str, Any]:
    """Resample and serialize OHLCV rows into the frontend payload shape."""
    if df_source.empty:
        return {}

    resampled = resample_ohlcv_data(df_source, timerange)
    if resampled is None or resampled.empty:
        return {}
    return serialize_ohlcv_dataframe(resampled, offset)


def build_pair_ohlcv_payload(
    df_source: pd.DataFrame | None,
    timerange: str,
    offset: float,
    *,
    live_candle: dict[str, float | str] | None = None,
) -> str | dict[str, Any]:
    """Build the chart payload for live/stored pair OHLCV data."""
    source = df_source.copy() if df_source is not None else pd.DataFrame()
    if live_candle is not None:
        source = append_live_candle(source, live_candle)
    return build_resampled_ohlcv_payload(source, timerange, offset)


def build_archived_ohlcv_payload(
    df_source: pd.DataFrame | None,
    timerange: str,
    offset: float,
) -> str | dict[str, Any]:
    """Build the chart payload for archived replay OHLCV data."""
    source = df_source.copy() if df_source is not None else pd.DataFrame()
    return build_resampled_ohlcv_payload(source, timerange, offset)


def _fresh_iana_zone(tzinfo: Any) -> ZoneInfo | None:
    """Resolve a binary TZif tzinfo to a fresh IANA-backed ``ZoneInfo``.

    ``dateutil``'s ``gettz`` and ``pytz`` hand back tzinfo objects whose
    transition tables are baked into the OS-shipped ``TZif`` binary, which
    stops at ~2037 on most systems. For any instant past that boundary the
    stale offset is reused, producing off-by-an-hour DST answers. The
    stdlib ``zoneinfo`` database resolves the same IANA name through a
    separately-updated data source, which has current far-future rules.
    """
    key = getattr(tzinfo, "key", None)
    if key:
        try:
            return ZoneInfo(str(key))
        except (ValueError, ZoneInfoNotFoundError):
            return None
    path = getattr(tzinfo, "_filename", None)
    if path is None:
        return None
    path_str = str(path)
    match = re.search(r"zoneinfo/", path_str, re.IGNORECASE)
    if match is not None:
        name = path_str[match.end() :].strip(os.sep)
        try:
            return ZoneInfo(name)
        except (ValueError, ZoneInfoNotFoundError):
            return None
    return None


def _reanchor_stale_tz(value: Any) -> Any:
    """Re-resolve a tz-aware value through a fresh IANA zone when available.

    No-op for naive timestamps and for any tzinfo we cannot resolve to a
    ``ZoneInfo``. Wall-clock and ``fold`` are preserved (Python's
    ``datetime.replace`` keeps both); only the ``tzinfo`` changes.
    """
    tzinfo = getattr(value, "tzinfo", None)
    if tzinfo is None:
        return value
    zone = _fresh_iana_zone(tzinfo)
    if zone is None:
        return value
    try:
        return value.replace(tzinfo=zone)
    except (TypeError, ValueError):
        return value


def _column_should_reanchor(series: pd.Series) -> bool:
    """Whether to re-anchor far-future tz-aware timestamps in this column.

    Numeric columns keep the original pandas unit inference untouched;
    tz-aware ``datetime64[<tz>]`` dtypes are re-anchored as a whole, and
    object-dtype columns are scanned lazily so a single tz-aware element
    among naive ones still triggers the re-anchoring pass.
    """
    dtype = series.dtype
    unit_kind = dtype.kind
    if unit_kind in ("i", "u", "f", "b"):
        return False
    if unit_kind == "M" and getattr(dtype, "tz", None) is not None:
        return True
    # object dtype: only scan until we hit the first aware element.
    for value in series:
        if getattr(value, "tzinfo", None) is not None:
            return True
    return False


def timestamp_to_unix_seconds(timestamp: Any) -> float | None:
    """Convert arbitrary timestamp-like values to UTC unix seconds."""
    if pd.isna(timestamp):
        return None
    try:
        return pd.Timestamp(timestamp).timestamp()
    except (TypeError, ValueError):
        return None


def serialize_ohlcv_dataframe(df_source: pd.DataFrame, offset: float) -> str:
    """Convert an OHLCV DataFrame into the frontend payload JSON."""
    df = df_source.copy()
    offset_minutes = int(offset)
    offset_seconds = offset_minutes * 60
    # dateutil/pytz tzinfos carry a stale binary TZif whose transitions
    # stop at ~2037; re-anchor tz-aware inputs through the IANA zoneinfo
    # database so far-future instants resolve with current rules.
    column = df.get("timestamp")
    if column is not None and _column_should_reanchor(column):
        df["timestamp"] = df["timestamp"].map(_reanchor_stale_tz)
    timestamp_series = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["time"] = timestamp_series.map(timestamp_to_unix_seconds)
    df.dropna(subset=["time"], inplace=True)
    df["time"] = df["time"].astype(float) + float(offset_seconds)
    df.drop_duplicates(subset=["time"], inplace=True)
    df.drop("volume", axis=1, inplace=True)
    df.drop("timestamp", axis=1, inplace=True)
    return df.to_json(orient="records")


def build_live_candle_payload(
    snapshot: list[Any] | tuple[Any, ...] | None,
    symbol: str,
    start_timestamp: float,
) -> dict[str, float | str] | None:
    """Normalize a watcher live-candle snapshot into a DataFrame-ready row."""
    if not snapshot or len(snapshot) < 6:
        return None

    try:
        timestamp = float(snapshot[0])
        if timestamp <= float(start_timestamp):
            return None

        return {
            "timestamp": timestamp,
            "symbol": symbol,
            "open": float(snapshot[1]),
            "high": float(snapshot[2]),
            "low": float(snapshot[3]),
            "close": float(snapshot[4]),
            "volume": float(snapshot[5]),
        }
    except (TypeError, ValueError):
        return None


def resample_ohlcv_data(ohlcv: pd.DataFrame, timerange: str) -> pd.DataFrame | None:
    """Resample OHLCV data to the requested timerange."""
    df = pd.DataFrame(ohlcv)
    if df.empty:
        return None

    df["timestamp"] = pd.to_datetime(
        df["timestamp"].astype(float), utc=True, origin="unix", unit="ms"
    )
    df = df.set_index("timestamp")

    normalized_timerange = str(timerange or "").strip().lower().replace("min", "m")
    resample_rule: str | pd.Timedelta = normalized_timerange
    resample_kwargs: dict[str, Any] = {}
    match = re.fullmatch(r"(\d+)\s*([mhdw])", normalized_timerange)
    if match:
        interval = max(1, int(match.group(1)))
        unit = match.group(2)
        if unit == "m":
            resample_rule = pd.Timedelta(minutes=interval)
        elif unit == "h":
            resample_rule = pd.Timedelta(hours=interval)
        elif unit == "d":
            resample_rule = pd.Timedelta(days=interval)
        else:
            # Use fixed-duration 7-day windows anchored to Monday 00:00 UTC so
            # weekly charts align with exchange weekly candle timestamps and the
            # history sync window math.
            resample_rule = pd.Timedelta(days=interval * 7)
        if unit == "w":
            resample_kwargs["origin"] = pd.Timestamp(
                timeframe_bucket_origin_milliseconds(normalized_timerange),
                unit="ms",
                tz="UTC",
            )
        else:
            resample_kwargs["origin"] = "epoch"

    df_resample = df.resample(resample_rule, **resample_kwargs).agg(
        {
            "open": "first",
            "high": "max",
            "close": "last",
            "low": "min",
            "volume": "sum",
        }
    )
    df_resample.reset_index(inplace=True)
    df_resample.dropna(inplace=True)
    return df_resample
