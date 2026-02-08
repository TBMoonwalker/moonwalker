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


async def run(
    symbol: str, timerange: str, lengths: Iterable[int], lookback: int
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

    close = ensure_series(df, "close")

    print(f"Symbol: {symbol}")
    print(f"Timerange: {timerange} (resample={format_timerange(timerange)})")
    print(f"Raw rows: {len(df_raw)} Resampled rows: {len(df)}")
    describe_last(close, "Close")

    for length in lengths:
        compare_ema(close, length)

    # Show rebound check for ema_low (EMA20 with close[-2] / close[-3]).
    ema20 = talib.EMA(close, timeperiod=20).dropna()
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
    args = parser.parse_args()
    lengths = parse_lengths(args.lengths)

    return asyncio.run(run(args.symbol, args.timerange, lengths, args.lookback))


if __name__ == "__main__":
    raise SystemExit(main())
