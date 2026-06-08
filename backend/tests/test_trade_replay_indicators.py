"""Trade replay strategy indicator regression coverage."""

from __future__ import annotations

from typing import Any

import pytest
from service import trade_replay_indicators as replay_module
from service.trade_replay_indicators import (
    ReplayIndicatorCandle,
    TradeReplayIndicatorService,
)

DEAL_ID = "11111111-1111-4111-8111-111111111111"


class _FakeTrades:
    def __init__(self, executions: list[dict[str, Any]]) -> None:
        self.executions = executions

    async def get_trade_executions(self, deal_id: str) -> list[dict[str, Any]]:
        return self.executions


class _FakeBuilder:
    calls: list[tuple[str, ...]] = []
    build_calls: list[tuple[int, int]] = []
    warmup_candles = 0

    def __init__(self, symbol: str, timeframe: str) -> None:
        self.symbol = symbol
        self.timeframe = timeframe

    async def collect_strategy_requirements(self, *slugs: str) -> list[str]:
        self.calls.append(tuple(slugs))
        return [slug for slug in slugs if slug != "missing_strategy"]

    async def build(
        self,
        indicators: Any,
        candles: list[ReplayIndicatorCandle],
        replay_start_index: int,
    ) -> list[dict[str, Any]]:
        self.build_calls.append((len(candles), replay_start_index))
        return [
            {
                "key": f"{self.symbol}:{self.timeframe}:ema",
                "label": "EMA 20",
                "pane": "price",
                "renderer": "line",
                "color": "#B7791F",
                "values": [
                    {
                        "time": candles[replay_start_index].timestamp,
                        "value": 100.0,
                    }
                ],
            }
        ]

    def required_warmup_candles(self) -> int:
        return self.warmup_candles


def _execution(strategy_name: str | None) -> dict[str, Any]:
    return {
        "deal_id": DEAL_ID,
        "symbol": "BTC/USDT",
        "side": "buy",
        "role": "base_order",
        "timestamp": "1700000000000",
        "strategy_name": strategy_name,
        "timeframe": "1m",
    }


def _candle(index: int) -> ReplayIndicatorCandle:
    price = 100.0 + index
    return ReplayIndicatorCandle(
        timestamp=1_700_000_000_000 + index * 60_000,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=10.0,
    )


@pytest.mark.asyncio
async def test_replay_indicators_return_series_for_persisted_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deals with a ledger strategy return indicator overlays."""
    _FakeBuilder.calls = []
    _FakeBuilder.build_calls = []
    _FakeBuilder.warmup_candles = 0
    service = TradeReplayIndicatorService(_FakeTrades([_execution("ema20_swing")]))

    async def fake_load_candles(
        *args: Any, **kwargs: Any
    ) -> list[ReplayIndicatorCandle]:
        return [_candle(0), _candle(1)]

    monkeypatch.setattr(service, "_load_candles", fake_load_candles)
    monkeypatch.setattr(replay_module, "StrategyChartIndicatorBuilder", _FakeBuilder)

    payload = await service.get_indicators(
        DEAL_ID, "1h", 1_700_000_000_000, 1_700_000_060_000
    )

    assert payload["source"] == "execution_ledger"
    assert payload["timeframe"] == "1h"
    assert payload["strategies"] == ["ema20_swing"]
    assert payload["indicators"][0]["label"] == "EMA 20"
    assert _FakeBuilder.calls == [("ema20_swing",)]


@pytest.mark.asyncio
async def test_replay_indicators_collect_all_unique_sidestep_strategies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sidestep campaign executions expose all unique persisted strategies."""
    _FakeBuilder.calls = []
    _FakeBuilder.build_calls = []
    _FakeBuilder.warmup_candles = 0
    service = TradeReplayIndicatorService(
        _FakeTrades(
            [
                _execution("sidestep_exit"),
                _execution("sidestep_reentry"),
                _execution("sidestep_exit"),
            ]
        )
    )

    async def fake_load_candles(
        *args: Any, **kwargs: Any
    ) -> list[ReplayIndicatorCandle]:
        return [_candle(0), _candle(1)]

    monkeypatch.setattr(service, "_load_candles", fake_load_candles)
    monkeypatch.setattr(replay_module, "StrategyChartIndicatorBuilder", _FakeBuilder)

    payload = await service.get_indicators(
        DEAL_ID, "15m", 1_700_000_000_000, 1_700_000_060_000
    )

    assert payload["strategies"] == ["sidestep_exit", "sidestep_reentry"]
    assert _FakeBuilder.calls == [("sidestep_exit", "sidestep_reentry")]


@pytest.mark.asyncio
async def test_replay_indicators_backfill_legacy_missing_strategy_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy executions without strategy metadata use configured backfill."""
    _FakeBuilder.calls = []
    _FakeBuilder.build_calls = []
    _FakeBuilder.warmup_candles = 0

    async def fake_config() -> dict[str, Any]:
        return {"signal_strategy": None, "dca_strategy": "ema_swing"}

    service = TradeReplayIndicatorService(
        _FakeTrades([_execution(None)]),
        config_snapshot_provider=fake_config,
    )

    async def fake_load_candles(
        *args: Any, **kwargs: Any
    ) -> list[ReplayIndicatorCandle]:
        return [_candle(0), _candle(1)]

    monkeypatch.setattr(service, "_load_candles", fake_load_candles)
    monkeypatch.setattr(replay_module, "StrategyChartIndicatorBuilder", _FakeBuilder)

    payload = await service.get_indicators(
        DEAL_ID, "1h", 1_700_000_000_000, 1_700_000_060_000
    )

    assert payload["source"] == "legacy_config_backfill"
    assert payload["strategies"] == ["ema_swing"]
    assert payload["indicators"][0]["label"] == "EMA 20"
    assert _FakeBuilder.calls == [("ema_swing",)]


@pytest.mark.asyncio
async def test_replay_indicators_return_empty_when_legacy_backfill_has_no_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy executions without configured strategies stay quiet."""

    async def fake_config() -> dict[str, Any]:
        return {"signal_strategy": None, "dca_strategy": None}

    service = TradeReplayIndicatorService(
        _FakeTrades([_execution(None)]),
        config_snapshot_provider=fake_config,
    )

    async def fail_load_candles(*args: Any) -> list[ReplayIndicatorCandle]:
        raise AssertionError("strategy-less legacy rows should not load candles")

    monkeypatch.setattr(service, "_load_candles", fail_load_candles)

    payload = await service.get_indicators(
        DEAL_ID, "1h", 1_700_000_000_000, 1_700_000_060_000
    )

    assert payload == {
        "indicators": [],
        "strategies": [],
        "timeframe": "1h",
        "source": "execution_ledger",
    }


@pytest.mark.asyncio
async def test_replay_indicators_skip_missing_strategy_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unavailable strategies are skipped without failing available overlays."""
    _FakeBuilder.calls = []
    _FakeBuilder.build_calls = []
    _FakeBuilder.warmup_candles = 0
    service = TradeReplayIndicatorService(
        _FakeTrades([_execution("missing_strategy"), _execution("ema20_swing")])
    )

    async def fake_load_candles(
        *args: Any, **kwargs: Any
    ) -> list[ReplayIndicatorCandle]:
        return [_candle(0), _candle(1)]

    monkeypatch.setattr(service, "_load_candles", fake_load_candles)
    monkeypatch.setattr(replay_module, "StrategyChartIndicatorBuilder", _FakeBuilder)

    payload = await service.get_indicators(
        DEAL_ID, "1h", 1_700_000_000_000, 1_700_000_060_000
    )

    assert payload["strategies"] == ["ema20_swing"]
    assert payload["indicators"][0]["values"][0]["value"] == 100.0
    assert _FakeBuilder.calls == [("missing_strategy", "ema20_swing")]


@pytest.mark.asyncio
async def test_replay_indicators_load_warmup_before_visible_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long EMAs get source history while chart output starts at visible candles."""
    _FakeBuilder.calls = []
    _FakeBuilder.build_calls = []
    _FakeBuilder.warmup_candles = 3
    service = TradeReplayIndicatorService(_FakeTrades([_execution("ema_swing")]))
    visible_start = 1_700_000_000_000
    visible_end = visible_start + 60 * 60 * 1000
    expected_start = visible_start - 3 * 60 * 60 * 1000

    async def fake_load_candles(
        deal_id: str,
        symbol: str,
        timerange: str,
        start_ms: int,
        end_ms: int,
        *,
        visible_start_ms: int | None = None,
    ) -> list[ReplayIndicatorCandle]:
        assert start_ms == expected_start
        assert end_ms == visible_end
        assert visible_start_ms == visible_start
        return [
            ReplayIndicatorCandle(
                timestamp=expected_start + index * 60 * 60 * 1000,
                open=100.0 + index,
                high=100.0 + index,
                low=100.0 + index,
                close=100.0 + index,
                volume=10.0,
            )
            for index in range(5)
        ]

    monkeypatch.setattr(service, "_load_candles", fake_load_candles)
    monkeypatch.setattr(replay_module, "StrategyChartIndicatorBuilder", _FakeBuilder)

    payload = await service.get_indicators(
        DEAL_ID,
        "1h",
        visible_start,
        visible_end,
    )

    assert payload["strategies"] == ["ema_swing"]
    assert payload["indicators"][0]["values"][0]["time"] == visible_start
    assert _FakeBuilder.build_calls == [(5, 3)]
