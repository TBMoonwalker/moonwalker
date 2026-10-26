"""Cross-mode graph, causal higher-timeframe and immutable-version regressions."""

import copy
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest
import talib
from service.accumulation.strategy import (
    AccumulationCandle,
    AccumulationParameters,
    build_accumulation_strategy_document,
    calculate_accumulation_market,
    parse_accumulation_strategy_document,
)
from service.shared_accumulation import (
    legacy_accumulation_graph,
    regime_accumulation_graph,
)
from service.strategy_conditions import (
    aggregate_frame,
    candle_frame,
    evaluate_conditions,
    graph_history,
    indicator_history,
    indicator_series,
)
from service.strategy_persistence import validate_strategy_ir
from service.strategy_runtime import EvaluationContext, _evaluate_root

HOUR = 3_600_000


def candles(count=1300, trend=-0.1):
    close = 1000 + np.arange(count) * trend + np.sin(np.arange(count) / 3)
    return [
        AccumulationCandle(
            (i + 1) * HOUR, str(price), str(price + 2), str(price - 2), str(price)
        )
        for i, price in enumerate(close)
    ]


@pytest.mark.parametrize(
    "name,fn",
    [
        ("atr", talib.ATR),
        ("adx", talib.ADX),
        ("plus_di", talib.PLUS_DI),
        ("minus_di", talib.MINUS_DI),
    ],
)
def test_directional_indicators_use_shared_talib_calculation(name, fn):
    frame = candle_frame(candles())
    result = indicator_series(frame, {"indicator": name, "length": 14})
    pd.testing.assert_series_equal(
        result, fn(frame.high, frame.low, frame.close, timeperiod=14)
    )


def test_normalized_ema_slope_and_discount_and_zero_atr():
    frame = candle_frame(candles())
    ema = talib.EMA(frame.close, timeperiod=50)
    atr = talib.ATR(frame.high, frame.low, frame.close, timeperiod=14)
    params = {"length": 50, "atr_length": 14, "slope_period": 6}
    pd.testing.assert_series_equal(
        indicator_series(frame, {**params, "indicator": "ema_slope"}),
        (ema - ema.shift(6)) / atr,
    )
    pd.testing.assert_series_equal(
        indicator_series(frame, {**params, "indicator": "ema_distance_atr"}),
        (ema - frame.close) / atr,
    )
    frame.loc[:, :] = 100
    assert indicator_series(frame, {**params, "indicator": "ema_slope"}).isna().all()


def test_higher_timeframe_uses_complete_contiguous_bars_only():
    frame = candle_frame(candles(13))
    aggregated = aggregate_frame(frame, "1h", "4h")
    assert list(aggregated.index) == [4 * HOUR, 8 * HOUR, 12 * HOUR]
    assert aggregated.iloc[-1]["close"] == frame.loc[12 * HOUR, "close"]
    pd.testing.assert_frame_equal(
        aggregated, aggregate_frame(frame.iloc[:12], "1h", "4h")
    )
    assert list(aggregate_frame(frame.drop(6 * HOUR), "1h", "4h").index) == [
        4 * HOUR,
        12 * HOUR,
    ]


def test_shared_preset_validates_and_rejects_uptrend():
    graph = regime_accumulation_graph()
    assert validate_strategy_ir(graph)["status"] == "valid"
    assert graph_history(graph, "1h") == 1240
    assert not evaluate_conditions(graph, candle_frame(candles(trend=0.1)), "1h")
    assert not evaluate_conditions(graph, candle_frame(candles(200)), "1h")
    assert evaluate_conditions(graph, candle_frame(candles(trend=-0.5)), "1h")


def test_prefix_causality_and_gap_fail_closed():
    graph = regime_accumulation_graph()
    frame = candle_frame(candles(1400, -0.2))
    before = evaluate_conditions(graph, frame.iloc[:1300], "1h")
    frame.iloc[1300:, :] = 1_000_000
    assert evaluate_conditions(graph, frame.iloc[:1300], "1h") == before
    assert not evaluate_conditions(graph, frame.iloc[:1300].drop(1100 * HOUR), "1h")


@pytest.mark.parametrize("mutation", ["state", "cycle", "nan", "timeframe", "length"])
def test_accumulation_compatibility_rejects_unsafe_graphs(mutation):
    graph = regime_accumulation_graph()
    if mutation == "state":
        graph["nodes"][0]["type"] = "fresh_signal_state"
    elif mutation == "cycle":
        graph["connections"].append({"source": graph["root"], "target": graph["root"]})
    elif mutation == "nan":
        next(node for node in graph["nodes"] if node["type"] == "constant_value")[
            "params"
        ]["value"] = float("nan")
    elif mutation == "timeframe":
        graph["nodes"][0]["params"]["timeframe"] = "5m"
    else:
        graph["nodes"][0]["params"]["length"] = 0
    assert validate_strategy_ir(graph)["status"] == "invalid"
    with pytest.raises(ValueError):
        parse_accumulation_strategy_document(graph)


def test_legacy_document_is_unchanged_and_graph_retains_native_parameters():
    document = build_accumulation_strategy_document()
    original = copy.deepcopy(document)
    graph = legacy_accumulation_graph(document, "test", "Legacy", False)
    parameters = parse_accumulation_strategy_document(graph)
    assert graph["accumulation"] == asdict(AccumulationParameters())
    assert document == original
    assert parameters.history_length == AccumulationParameters().history_length
    assert calculate_accumulation_market(
        candles(253), parameters, close_ms=253 * HOUR
    ).conditions_match


@pytest.mark.asyncio
async def test_dca_and_accumulation_evaluate_identical_closed_snapshot():
    graph = regime_accumulation_graph()
    parameters = parse_accumulation_strategy_document(graph)
    source = candles(parameters.history_length, -0.5)
    assert calculate_accumulation_market(
        source, parameters, close_ms=source[-1].close_ms
    ).conditions_match
    frame = candle_frame(source)
    # DCA data index denotes opening timestamps; accumulation denotes closing timestamps.
    frame.index = pd.to_datetime(frame.index - HOUR, unit="ms", utc=True)
    provider = SimpleNamespace(condition_frame=AsyncMock(return_value=frame))
    context = EvaluationContext(
        "regime_accumulation",
        "1h",
        "BTC/USDC",
        "buy",
        provider,
        candle_index=len(frame) - 1,
    )
    assert (
        await _evaluate_root(graph, context)
        == calculate_accumulation_market(
            source, parameters, close_ms=source[-1].close_ms
        ).conditions_match
    )


def test_macd_warmup_and_parameter_bounds():
    assert indicator_history({"indicator": "macd_line", "slow_period": 200}) >= 1200
    with pytest.raises(ValueError):
        indicator_history({"indicator": "macd_line", "fast_period": 26})


@pytest.mark.asyncio
async def test_chart_exposes_shared_higher_timeframe_conditions_without_partial_bar():
    from service.backtest import BacktestData, OhlcvCandle, candles_to_dataframe
    from service.indicators import Indicators
    from service.strategy_chart_indicators import StrategyChartIndicatorBuilder

    source = candles(1301, -0.5)
    chart = [
        OhlcvCandle(
            row.close_ms - HOUR,
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            1,
        )
        for row in source
    ]
    provider = Indicators(data=BacktestData(candles_to_dataframe(chart)))
    builder = StrategyChartIndicatorBuilder("BTC/USDC", "1h")
    builder.collect_ir_requirements(regime_accumulation_graph())
    assert builder.required_warmup_candles() == 1240
    series = await builder.build(provider, chart, 1240)
    assert {row["pane"] for row in series} == {"atr_units", "dmi"}
    slope = next(row for row in series if row["label"].startswith("EMA slope"))
    # The final 1h close is inside a forming 4h bar, so its last known regime is unchanged.
    assert slope["values"][-1]["value"] == slope["values"][-2]["value"]


@pytest.mark.parametrize(
    "params",
    [
        {"indicator": "ema", "length": "invalid"},
        {"indicator": "atr", "timeframe": "2h"},
        {"indicator": "atr", "timeframe": ["4h"]},
        {"indicator": "ema_slope", "sample": "future"},
        {"indicator": "macd_line", "fast_period": 30, "slow_period": 26},
    ],
)
def test_shared_indicator_invalid_parameters_are_validation_errors(params):
    graph = regime_accumulation_graph()
    graph["nodes"][0]["params"] = params
    result = validate_strategy_ir(graph)
    assert result["status"] == "invalid"
    assert any(error["group"] == "Indicators" for error in result["blocking_errors"])


def test_higher_timeframe_dca_graphs_validate_without_accumulation_settings():
    graph = regime_accumulation_graph()
    del graph["accumulation"]
    assert validate_strategy_ir(graph)["status"] == "valid"
    graph["nodes"][0]["type"] = "fresh_signal_state"
    result = validate_strategy_ir(graph)
    assert result["status"] == "invalid"
    assert any(
        row["group"] == "Timeframe compatibility" for row in result["blocking_errors"]
    )
