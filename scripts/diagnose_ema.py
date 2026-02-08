#!/usr/bin/env python3
"""Diagnose EMA calculations by comparing TA-Lib to pandas on the same data."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Iterable

import pandas as pd
import talib

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import helper  # noqa: E402
from service.data import Data  # noqa: E402
from tortoise import Tortoise  # noqa: E402


def parse_lengths(raw: str) -> list[int]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return [int(p) for p in parts]


def pandas_ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def describe_last(series: pd.Series, label: str, n: int = 5) -> None:
    print(f"{label} (last {n}): {series.tail(n).to_list()}")


def compare_ema(close: pd.Series, length: int) -> None:
    ta = talib.EMA(close, timeperiod=length).dropna()
    pd_ema = pandas_ema(close, length).dropna()

    if ta.empty or pd_ema.empty:
        print(f"EMA {length}: insufficient data after dropna")
        return

    ta_last = ta.iloc[-1]
    pd_last = pd_ema.iloc[-1]
    diff = ta_last - pd_last
    pct = (diff / pd_last) * 100 if pd_last != 0 else 0

    print(
        f"EMA {length}: TA-Lib={ta_last:.8f} pandas={pd_last:.8f} diff={diff:.8f} ({pct:.6f}%)"
    )


def normalize_timerange(timerange: str) -> str:
    if timerange.endswith("m"):
        return f"{timerange[:-1]}Min"
    return timerange


def ensure_series(df: pd.DataFrame, name: str) -> pd.Series:
    series = df[name]
    if not isinstance(series, pd.Series):
        raise ValueError(f"Expected series for {name}")
    return series


def format_timerange(timerange: str) -> str:
    return normalize_timerange(timerange)


def print_rebound_checks(close: pd.Series, ema_20: float) -> None:
    if len(close.dropna()) < 3:
        print("Not enough close data for rebound check")
        return
    close_clean = close.dropna()
    close_minus_2 = close_clean.iloc[-2]
    close_minus_3 = close_clean.iloc[-3]
    print(
        f"Rebound check: close[-2]={close_minus_2:.8f} > ema20={ema_20:.8f} and close[-3]={close_minus_3:.8f} < ema20={ema_20:.8f}"
    )

def parse_datetime(value: str | None) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.to_datetime(value, errors="raise")
    if isinstance(timestamp, pd.Series):
        raise ValueError(f"Ambiguous datetime value: {value}")
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def filter_by_range(
    df: pd.DataFrame, start: pd.Timestamp | None, end: pd.Timestamp | None
) -> pd.DataFrame:
    if start is None and end is None:
        return df
    if start is not None and end is not None and start > end:
        raise ValueError("start must be before end")
    if not isinstance(df.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            df = df.set_index("timestamp", drop=False)
        else:
            raise ValueError("Expected DatetimeIndex or timestamp column to filter by range")
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df.index >= start
    if end is not None:
        mask &= df.index <= end
    return df.loc[mask]

def add_ema_low_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = ensure_series(df, "close")
    df["ema_20"] = talib.EMA(close, timeperiod=20)
    df["ema_50"] = talib.EMA(close, timeperiod=50)
    df["ema_100"] = talib.EMA(close, timeperiod=100)
    df["ema_200"] = talib.EMA(close, timeperiod=200)
    df["ema_20_pd"] = pandas_ema(close, 20)
    df["ema_50_pd"] = pandas_ema(close, 50)
    df["ema_100_pd"] = pandas_ema(close, 100)
    df["ema_200_pd"] = pandas_ema(close, 200)
    df["ema_20_diff"] = df["ema_20"] - df["ema_20_pd"]
    df["ema_50_diff"] = df["ema_50"] - df["ema_50_pd"]
    df["ema_100_diff"] = df["ema_100"] - df["ema_100_pd"]
    df["ema_200_diff"] = df["ema_200"] - df["ema_200_pd"]
    df["trend_ok"] = (
        (df["ema_20"] < df["ema_200"])
        & (df["ema_50"] < df["ema_200"])
        & (df["ema_100"] < df["ema_200"])
    )
    df["rebound_ok"] = (
        (close.shift(1) > df["ema_20"])
        & (close.shift(2) < df["ema_20"])
    )
    df["ema_low_signal"] = df["trend_ok"] & df["rebound_ok"]
    return df


def print_range_view(df: pd.DataFrame, max_rows: int) -> None:
    if df.empty:
        print("No rows available in the selected range")
        return
    view = df[
        [
            "timestamp",
            "close",
            "ema_20",
            "ema_20_pd",
            "ema_20_diff",
            "ema_50",
            "ema_50_pd",
            "ema_50_diff",
            "ema_100",
            "ema_100_pd",
            "ema_100_diff",
            "ema_200",
            "ema_200_pd",
            "ema_200_diff",
            "trend_ok",
            "rebound_ok",
            "ema_low_signal",
        ]
    ].copy()
    view["timestamp"] = view["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S%z")
    if len(view) > max_rows:
        print(f"Showing first {max_rows} rows (total {len(view)} rows)")
        view = view.head(max_rows)
    print(view.to_string(index=False))


async def run(
    symbol: str,
    timerange: str,
    lengths: Iterable[int],
    lookback: int,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    max_rows: int,
) -> int:
    db_url = os.getenv(
        "MOONWALKER_DB_URL",
        f"sqlite://{os.path.join(BACKEND_DIR, 'db', 'trades.sqlite')}",
    )
    await Tortoise.init(db_url=db_url, modules={"models": ["model"]})
    data = Data()
    df_raw = await data.get_data_for_pair(symbol, timerange, lookback)
    if df_raw is None or df_raw.empty:
        print("No raw data available for symbol")
        await Tortoise.close_connections()
        return 1

    df = data.resample_data(df_raw, timerange)
    if df is None or df.empty:
        print("No resampled data available for symbol")
        await Tortoise.close_connections()
        return 1

    print(f"Symbol: {symbol}")
    print(f"Timerange: {timerange} (resample={format_timerange(timerange)})")
    print(f"Raw rows: {len(df_raw)} Resampled rows: {len(df)}")

    df_with_ema = add_ema_low_columns(df)

    if start or end:
        start_label = start.isoformat(sep=" ") if start else "-"
        end_label = end.isoformat(sep=" ") if end else "-"
        print(f"Range filter: {start_label} to {end_label}")
        try:
            df_range = filter_by_range(df_with_ema, start, end)
        except ValueError as exc:
            print(f"Invalid time range: {exc}")
            await Tortoise.close_connections()
            return 1
        if df_range.empty:
            print("No resampled data available for the selected time range")
            await Tortoise.close_connections()
            return 1
        print_range_view(df_range, max_rows)
        await Tortoise.close_connections()
        return 0

    close = ensure_series(df_with_ema, "close")
    describe_last(close, "Close")
    for length in lengths:
        compare_ema(close, length)

    # Show rebound check for ema_low (EMA20 with close[-2] / close[-3]).
    ema20 = df_with_ema["ema_20"].dropna()
    if not ema20.empty:
        print_rebound_checks(close, ema20.iloc[-1])

    await Tortoise.close_connections()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", help="Symbol like BTC/USDT")
    parser.add_argument("timerange", help="Timerange like 1m, 15m, 1h")
    parser.add_argument(
        "--lengths",
        default="20,50,100,200",
        help="Comma-separated EMA lengths (default: 20,50,100,200)",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=400,
        help="Number of candles to request (default: 400)",
    )
    parser.add_argument(
        "--start",
        help='Start timestamp (e.g. "2026-02-06 01:00:00")',
    )
    parser.add_argument(
        "--end",
        help='End timestamp (e.g. "2026-02-06 05:00:00")',
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=200,
        help="Max rows to print for a range filter (default: 200)",
    )
    args = parser.parse_args()
    lengths = parse_lengths(args.lengths)

    try:
        start = parse_datetime(args.start)
        end = parse_datetime(args.end)
    except ValueError as exc:
        print(f"Invalid datetime: {exc}")
        return 1

    return asyncio.run(
        run(
            args.symbol,
            args.timerange,
            lengths,
            args.lookback,
            start,
            end,
            args.max_rows,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
