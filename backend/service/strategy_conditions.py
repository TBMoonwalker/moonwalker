"""Shared, causal condition graphs for DCA and accumulation candle snapshots."""

from __future__ import annotations

import math
import operator
from collections.abc import Sequence
from typing import Any

import pandas as pd
import talib
from service.data_timeframes import (
    timeframe_bucket_origin_milliseconds,
    timeframe_to_milliseconds,
)

SHARED_INDICATORS = frozenset(
    {"atr", "adx", "plus_di", "minus_di", "ema_slope", "ema_distance_atr"}
)
PURE_NODE_TYPES = frozenset(
    {
        "indicator",
        "constant_value",
        "close_price",
        "low_price",
        "high_price",
        "comparison",
        "all",
        "any",
    }
)
TIMEFRAMES = frozenset({"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"})
SAMPLES = {"current": -1, "previous": -2, "two_back": -3}


def indicator_history(params: dict[str, Any]) -> int:
    """Bound warmup, including stable Wilder/EMA initialization and sampled slope."""
    length = params.get("length", 14)
    if type(length) is not int or not 2 <= length <= 500:
        raise ValueError("Indicator length must be an integer from 2 to 500.")
    slope = params.get("slope_period", 6)
    if type(slope) is not int or not 1 <= slope <= 100:
        raise ValueError("Slope period must be an integer from 1 to 100.")
    atr = params.get("atr_length", 14)
    if type(atr) is not int or not 2 <= atr <= 100:
        raise ValueError("ATR length must be an integer from 2 to 100.")
    macd_history = 0
    if str(params.get("indicator", "")).startswith("macd_"):
        periods = [
            params.get(key, default)
            for key, default in [
                ("fast_period", 12),
                ("slow_period", 26),
                ("signal_period", 9),
            ]
        ]
        if (
            any(type(period) is not int or not 2 <= period <= 500 for period in periods)
            or periods[0] >= periods[1]
        ):
            raise ValueError("MACD requires bounded integer periods and fast < slow.")
        macd_history = (periods[1] + periods[2]) * 6
    deviations = params.get("standard_deviations", 2)
    if (
        not isinstance(deviations, (float, int))
        or not math.isfinite(deviations)
        or not 0 < deviations <= 10
    ):
        raise ValueError("Standard deviations must be finite and between 0 and 10.")
    if params.get("sample", "current") not in SAMPLES:
        raise ValueError("Unsupported indicator sample.")
    warmup = length * (
        18
        if params.get("indicator") in {"atr", "adx", "plus_di", "minus_di", "rsi"}
        else 6
    )
    return max(200, warmup, atr * 18, macd_history) + slope + 3


def graph_history(ir: dict[str, Any], timeframe: str) -> int:
    """Validate an accumulation-compatible graph and bound its base-bar history."""
    if timeframe not in TIMEFRAMES:
        raise ValueError("Unsupported graph timeframe.")
    base = timeframe_to_milliseconds(timeframe)
    nodes = ir.get("nodes")
    edges = ir.get("connections", [])
    if (
        not isinstance(nodes, list)
        or not 1 <= len(nodes) <= 128
        or not isinstance(edges, list)
        or len(edges) > 512
    ):
        raise ValueError(
            "Condition graphs require 1..128 nodes and at most 512 connections."
        )
    if any(
        not isinstance(node, dict)
        or not isinstance(node.get("id"), str)
        or not node["id"]
        for node in nodes
    ):
        raise ValueError("Every condition node needs a string id.")
    by_id = {node["id"]: node for node in nodes}
    if len(by_id) != len(nodes) or ir.get("root") not in by_id:
        raise ValueError("Condition graph needs unique nodes and a valid decision.")
    history = 0
    for node in nodes:
        if node.get("type") not in PURE_NODE_TYPES:
            raise ValueError(
                "Accumulation supports pure condition graphs; legacy state nodes remain DCA-only."
            )
        params = node.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("Node parameters must be an object.")
        if node["type"] == "constant_value":
            raw = params.get("value")
            if not isinstance(raw, (int, float)) or not math.isfinite(raw):
                raise ValueError("Shared conditions require finite numeric constants.")
        target = params.get("timeframe") or timeframe
        if target not in TIMEFRAMES:
            raise ValueError("Unsupported indicator timeframe.")
        interval = timeframe_to_milliseconds(target)
        if interval < base or interval % base:
            raise ValueError(
                "Indicator timeframe must be the base timeframe or an exact higher multiple."
            )
        count = indicator_history(params) if node["type"] == "indicator" else 50
        history = max(history, (count + 1) * (interval // base))
    if history > 12000:
        raise ValueError("Condition graph warmup exceeds 12000 base candles.")
    incoming: dict[str, list[str]] = {key: [] for key in by_id}
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("Connections must be objects.")
        if edge.get("target") not in by_id or edge.get("source") not in by_id:
            raise ValueError("Condition graph has a missing connection node.")
        incoming[edge["target"]].append(edge["source"])
    visited: set[str] = set()
    active: set[str] = set()

    def visit(key: str) -> None:
        if key in active:
            raise ValueError("Condition graph must not contain cycles.")
        if key in visited:
            return
        active.add(key)
        for source in incoming[key]:
            visit(source)
        active.remove(key)
        visited.add(key)

    for key in by_id:
        visit(key)
    return history


def indicator_series(frame: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """Calculate shared indicators causally; no forward shifts or centered windows."""
    name = params.get("indicator")
    length = int(
        params.get("length", 14 if name in SHARED_INDICATORS or name == "rsi" else 20)
    )
    close = frame["close"].astype(float)
    if name == "ema":
        return talib.EMA(close, timeperiod=length)
    if name == "rsi":
        return talib.RSI(close, timeperiod=length)
    if str(name).startswith("bollinger_"):
        upper, middle, lower = talib.BBANDS(
            close,
            timeperiod=length,
            nbdevup=float(params.get("standard_deviations", 2)),
            nbdevdn=float(params.get("standard_deviations", 2)),
        )
        return {
            "bollinger_upper": upper,
            "bollinger_middle": middle,
            "bollinger_lower": lower,
            "bollinger_bandwidth": (upper - lower) / middle * 100,
        }[name]
    if str(name).startswith("macd_"):
        line, signal, histogram = talib.MACD(
            close,
            fastperiod=int(params.get("fast_period", 12)),
            slowperiod=int(params.get("slow_period", 26)),
            signalperiod=int(params.get("signal_period", 9)),
        )
        return {"macd_line": line, "macd_signal": signal, "macd_histogram": histogram}[
            name
        ]
    high, low = frame["high"].astype(float), frame["low"].astype(float)
    if name in {"atr", "adx", "plus_di", "minus_di"}:
        fn = {
            "atr": talib.ATR,
            "adx": talib.ADX,
            "plus_di": talib.PLUS_DI,
            "minus_di": talib.MINUS_DI,
        }[name]
        return fn(high, low, close, timeperiod=length)
    if name in {"ema_slope", "ema_distance_atr"}:
        ema = talib.EMA(close, timeperiod=length)
        atr = talib.ATR(
            high, low, close, timeperiod=int(params.get("atr_length", 14))
        ).replace(0, float("nan"))
        if name == "ema_slope":
            return (ema - ema.shift(int(params.get("slope_period", 6)))) / atr
        return (ema - close) / atr
    raise ValueError("Unsupported graph indicator.")


def candle_frame(candles: Sequence[Any]) -> pd.DataFrame:
    """Create a frame whose index denotes candle closes, not opening timestamps."""
    return pd.DataFrame(
        {
            key: [float(getattr(candle, key)) for candle in candles]
            for key in ("open", "high", "low", "close")
        },
        index=pd.Index([candle.close_ms for candle in candles], name="close_ms"),
    )


def aggregate_frame(frame: pd.DataFrame, base: str, target: str) -> pd.DataFrame:
    """Use only complete higher-timeframe candles available at this base close."""
    if frame.empty or target == base:
        return frame
    interval = timeframe_to_milliseconds(target)
    step = timeframe_to_milliseconds(base)
    origin = timeframe_bucket_origin_milliseconds(target)
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        return frame.iloc[:0]
    source = frame.assign(_timestamp=frame.index)
    buckets = (
        (frame.index.to_numpy(dtype="int64") - origin - 1) // interval + 1
    ) * interval + origin
    grouped = source.groupby(buckets).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        count=("_timestamp", "count"),
        first=("_timestamp", "min"),
        last=("_timestamp", "max"),
    )
    complete = grouped.loc[
        (grouped.index <= int(frame.index[-1]))
        & (grouped["count"] == interval // step)
        & (grouped["first"] == grouped.index - interval + step)
        & (grouped["last"] == grouped.index)
    ]
    return complete[["open", "high", "low", "close"]].rename_axis("close_ms")


def evaluate_conditions(
    ir: dict[str, Any], frame: pd.DataFrame, timeframe: str
) -> bool:
    """Evaluate the same pure graph on closed snapshots in either trading mode."""
    required = graph_history(ir, timeframe)
    if len(frame) < required:
        return False
    frame = frame.iloc[-required:]
    step = timeframe_to_milliseconds(timeframe)
    if not frame.index.is_unique or any(
        b - a != step for a, b in zip(frame.index, frame.index[1:])
    ):
        return False
    if frame.empty:
        return False
    by_id = {node["id"]: node for node in ir["nodes"]}
    edges = ir.get("connections", [])
    memo: dict[str, Any] = {}
    frames = {timeframe: frame}
    comparisons = {
        "less_than": operator.lt,
        "less_or_equal": operator.le,
        "greater_than": operator.gt,
        "greater_or_equal": operator.ge,
        "equals": operator.eq,
        "not_equals": operator.ne,
    }

    def value(key: str) -> Any:
        if key in memo:
            return memo[key]
        node = by_id[key]
        kind, params = node["type"], node.get("params") or {}
        inputs = [edge for edge in edges if edge["target"] == key]
        result: Any = None
        if kind in {"all", "any"}:
            values = [value(edge["source"]) is True for edge in inputs]
            result = bool(values) and (all(values) if kind == "all" else any(values))
        elif kind == "constant_value":
            result = params.get("value")
        elif kind == "comparison":
            ports = {
                {"left": "value1", "right": "value2"}.get(
                    edge.get("target_input")
                    or edge.get("targetInput")
                    or edge.get("input"),
                    edge.get("target_input")
                    or edge.get("targetInput")
                    or edge.get("input"),
                ): edge["source"]
                for edge in inputs
            }
            left = value(ports["value1"]) if "value1" in ports else None
            right = value(ports["value2"]) if "value2" in ports else None
            fn = comparisons.get(params.get("comparison", "equals"))
            if fn and left is not None and right is not None:
                try:
                    result = bool(fn(float(left), float(right)))
                except (TypeError, ValueError):
                    result = (
                        bool(fn(left, right)) if type(left) is type(right) else False
                    )
            else:
                result = False
        else:
            target = params.get("timeframe") or timeframe
            if target not in frames:
                frames[target] = aggregate_frame(frame, timeframe, target)
            selected = frames[target]
            sample = SAMPLES.get(params.get("sample", "current"), -1)
            series = (
                indicator_series(selected, params)
                if kind == "indicator" and not selected.empty
                else selected.get(
                    {
                        "close_price": "close",
                        "low_price": "low",
                        "high_price": "high",
                    }.get(kind, "close")
                )
            )
            if series is not None and len(series) >= abs(sample):
                raw = float(series.iloc[sample])
                if math.isfinite(raw):
                    result = raw
        memo[key] = result
        return result

    return value(ir["root"]) is True
