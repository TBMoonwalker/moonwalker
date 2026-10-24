"""Shared Backtest adapter uses historical data without trading or invented exits."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from controller import backtest as controller
from service import accumulation_backtest as adapter
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_strategy import AccumulationParameters
from service.backtest import BacktestValidationError, OhlcvCandle
from service.strategy_runtime import AccumulationStrategyVersion


@pytest.fixture
def history(monkeypatch):
    """Provide completed exchange candles around a fixed replay interval."""
    parameters = AccumulationParameters()
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 3, tzinfo=UTC)
    first = int(start.timestamp() * 1000)
    candles = []
    for offset in range(-parameters.history_length, 48):
        price = Decimal(100) if offset < 0 else Decimal(100) - offset
        candles.append(
            OhlcvCandle(
                first + offset * parameters.interval_ms,
                float(price + 1),
                float(price + 2),
                float(price - 1),
                float(price),
                100,
            )
        )
    fetch = AsyncMock(return_value=candles)
    load = AsyncMock(return_value=AccumulationStrategyVersion(7, "dip", 2, parameters))
    monkeypatch.setattr(adapter, "fetch_ohlcv", fetch)
    monkeypatch.setattr(adapter, "load_accumulation_strategy_version", load)
    return start, end, fetch, load


@pytest.mark.asyncio
async def test_backtest_fetches_warmup_and_maps_buys_to_shared_chart(history):
    start, end, fetch, load = history
    result = await adapter.run_accumulation_backtest(
        {},
        {
            "symbol": "BTC/USDC",
            "strategy_version_id": 7,
            "funding": "1000",
            "fee": 0.001,
        },
        start,
        end,
    )
    load.assert_awaited_once_with(7)
    assert fetch.await_args.args[2] == "1h"
    assert fetch.await_args.args[3] < int(start.timestamp() * 1000)
    assert result["stats"]["trade_mode"] == "accumulation"
    assert result["stats"]["candles_evaluated"] == 48
    assert result["chart"]["candles"][0]["time"] == int(start.timestamp())
    assert result["trades"] == []  # Unsold inventory is not a realized DCA exit.
    fills = result["accumulation"]["accumulation_trades"]
    assert fills and result["chart"]["markers"]
    assert (
        result["chart"]["markers"][0]["time"] == fills[0]["execution_open_ms"] // 1000
    )
    assert result["accumulation"]["fee_bps"] == "10.000"
    assert all(
        Decimal(row["contributed_quote"]) == 1000
        for row in result["accumulation"]["results"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"timeframe": "4h"},
        {"fee": "NaN"},
        {"funding": "0"},
        {"slippage_bps": "1001"},
        {"fixed_interval_candles": True},
        {"symbol": "BTC/USDC:USDC"},
    ],
)
async def test_invalid_inputs_never_fetch_history(history, changes):
    start, end, fetch, _ = history
    with pytest.raises((BacktestValidationError, AccumulationStateError)):
        await adapter.run_accumulation_backtest(
            {}, {"symbol": "BTC/USDC", "strategy_version_id": 7, **changes}, start, end
        )
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_warmup_is_reported_without_shifting_requested_range(history):
    start, end, fetch, _ = history
    fetch.return_value = fetch.return_value[1:]
    with pytest.raises(BacktestValidationError, match="warmup"):
        await adapter.run_accumulation_backtest(
            {}, {"symbol": "BTC/USDC", "strategy_version_id": 7}, start, end
        )


@pytest.mark.asyncio
async def test_normal_backtest_endpoint_dispatches_accumulation(monkeypatch):
    config = type("Snapshot", (), {"snapshot": lambda _: {"exchange": "binance"}})()
    monkeypatch.setattr(controller.Config, "instance", AsyncMock(return_value=config))
    run = AsyncMock(return_value={"stats": {"trade_mode": "accumulation"}})
    monkeypatch.setattr(controller, "run_accumulation_backtest", run)
    response = await controller._run_backtest(
        {
            "symbol": "BTC/USDC",
            "trade_mode": "accumulation",
            "strategy_version_id": 7,
            "start_date": "2025-01-01",
            "end_date": "2025-01-03",
        }
    )
    assert response.status_code == 200
    run.assert_awaited_once()


@pytest.mark.asyncio
async def test_backtest_applies_shared_graph_to_subsequent_buys(history):
    from dataclasses import replace

    from service.accumulation_strategy import (
        build_accumulation_strategy_document,
        parse_accumulation_strategy_document,
    )
    from service.shared_accumulation import legacy_accumulation_graph

    start, end, fetch, load = history
    graph = legacy_accumulation_graph(
        build_accumulation_strategy_document(), "shared", "Shared", False
    )
    graph["nodes"][0]["params"]["value"] = 0
    load.return_value = replace(
        load.return_value, parameters=parse_accumulation_strategy_document(graph)
    )
    blocked = await adapter.run_accumulation_backtest(
        {}, {"symbol": "BTC/USDC", "strategy_version_id": 7}, start, end
    )
    assert blocked["accumulation"]["accumulation_trades"] == []
    graph["nodes"][0]["params"]["value"] = 1
    load.return_value = replace(
        load.return_value, parameters=parse_accumulation_strategy_document(graph)
    )
    allowed = await adapter.run_accumulation_backtest(
        {}, {"symbol": "BTC/USDC", "strategy_version_id": 7}, start, end
    )
    assert allowed["accumulation"]["accumulation_trades"]


@pytest.mark.asyncio
async def test_backtest_uses_exchange_interval_instead_of_saved_base(history):
    start, end, fetch, load = history
    first = int(start.timestamp() * 1000)
    interval = 4 * 3600000
    warmup = load.return_value.parameters.history_length
    fetch.return_value = [
        OhlcvCandle(first + offset * interval, 100, 102, 98, 100, 1)
        for offset in range(-warmup, 12)
    ]
    result = await adapter.run_accumulation_backtest(
        {"timeframe": "4h"},
        {"symbol": "BTC/USDC", "strategy_version_id": 7, "timeframe": "4h"},
        start,
        end,
    )
    assert fetch.await_args.args[2] == "4h"
    assert load.return_value.parameters.timeframe == "1h"
    assert result["stats"]["timeframe"] == "4h"
    assert result["stats"]["candles_evaluated"] == 12


@pytest.mark.asyncio
async def test_exchange_timeframe_alias_is_consistent_with_backtest_request(history):
    start, end, _, _ = history
    result = await adapter.run_accumulation_backtest(
        {"timeframe": "60min"},
        {"symbol": "BTC/USDC", "strategy_version_id": 7, "timeframe": "60min"},
        start,
        end,
    )
    assert result["stats"]["timeframe"] == "1h"
