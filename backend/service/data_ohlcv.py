"""Pure OHLCV transformation helpers used by the data service."""

from __future__ import annotations

from typing import Any

import pandas as pd


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

    normalized_timerange = timerange
    if "m" in normalized_timerange:
        interval, _ = normalized_timerange.split("m")
        normalized_timerange = f"{interval}Min"

    df_resample = df.resample(normalized_timerange).agg(
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
