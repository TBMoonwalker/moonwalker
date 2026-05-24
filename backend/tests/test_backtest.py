"""Backtest backend regression coverage."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from controller import backtest as backtest_controller
from litestar import Litestar
from litestar.testing import TestClient
from service import backtest as backtest_service
from service import strategy_runtime
from service.analytics import compute_stats_from_trades
from service.backtest import (
    TRADE_MODE_SIDESTEP,
    Backtest,
    BacktestValidationError,
    DcaSimulator,
    OhlcvCandle,
    candles_to_dataframe,
    estimate_candle_count,
    validate_backtest_range,
)
from service.dca_math import (
    BacktestTradeState,
    calculate_safety_order_trigger_threshold,
)
from service.dca_safety_orders import calculate_static_deviations
from service.exchange import Exchange
from service.strategy_runtime import EvaluationContext


def _candle(index: int, close: float = 100.0) -> OhlcvCandle:
    timestamp = 1_700_000_000_000 + index * 60_000
    return OhlcvCandle(
        timestamp=timestamp,
        open_price=close,
        high=close,
        low=close,
        close=close,
        volume=10.0,
    )


def _make_state(
    *,
    entry_price: float = 100.0,
    fee: float = 0.0,
    safety_orders_count: int = 0,
) -> BacktestTradeState:
    amount = 100.0 / entry_price
    return BacktestTradeState(
        symbol="BTC/USDT",
        entry_price=entry_price,
        entry_amount=amount,
        entry_cost=100.0,
        fee=fee,
        entry_timestamp=1_000,
        safety_orders_count=safety_orders_count,
        total_amount=amount,
        total_cost=100.0,
    )


class _FakeIndicators:
    async def calculate_ema(self, symbol: str, timerange: str, lengths: list[int]):
        return {f"ema_{length}": 9999.0 for length in lengths}

    async def calculate_ema_series(
        self, symbol: str, timerange: str, length: int
    ) -> pd.Series:
        return pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])

    async def get_close_price(
        self, symbol: str, timerange: str, length: int
    ) -> pd.Series:
        return pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])


def _json(response: Any) -> dict[str, Any]:
    return json.loads(response.content)


def test_strategy_runtime_imports_cleanly() -> None:
    """Importing strategy_runtime is the first backtest runtime gate."""
    assert strategy_runtime.EvaluationContext.__name__ == "EvaluationContext"


@pytest.mark.asyncio
async def test_backtest_state_store_bypasses_strategy_graph_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backtest state must stay in memory and never touch live graph state."""

    async def fail_get_or_none(**kwargs: Any) -> None:
        raise AssertionError("StrategyGraphState DB read should not happen")

    async def fail_update_or_create(**kwargs: Any) -> None:
        raise AssertionError("StrategyGraphState DB write should not happen")

    monkeypatch.setattr(
        strategy_runtime.model.StrategyGraphState,
        "get_or_none",
        fail_get_or_none,
    )
    monkeypatch.setattr(
        strategy_runtime.model.StrategyGraphState,
        "update_or_create",
        fail_update_or_create,
    )

    context = EvaluationContext(
        slug="demo",
        timeframe="1m",
        symbol="BTC/USDT",
        side="buy",
        indicators=_FakeIndicators(),
        state_store={},
    )

    await strategy_runtime._remember_state(context, "state", [1.0, 2.0])
    assert await strategy_runtime._load_state(context, "state") == [1.0, 2.0]


@pytest.mark.asyncio
async def test_live_strategy_state_still_uses_persisted_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live graph evaluation keeps the existing persisted state behavior."""
    calls: list[dict[str, Any]] = []

    async def fake_get_or_none(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(value_json=json.dumps(7.0))

    monkeypatch.setattr(
        strategy_runtime.model.StrategyGraphState,
        "get_or_none",
        fake_get_or_none,
    )

    context = EvaluationContext(
        slug="demo",
        timeframe="1m",
        symbol="BTC/USDT",
        side="buy",
        indicators=_FakeIndicators(),
    )

    assert await strategy_runtime._load_state(context, "state") == 7.0
    assert calls == [
        {
            "strategy_slug": "demo",
            "state_key": "state",
            "symbol": "BTC/USDT",
            "timeframe": "1m",
        }
    ]


@pytest.mark.asyncio
async def test_backtest_ema_values_use_candle_index_not_final_scalar() -> None:
    """Backtest EMA scalars must not use final-candle indicator values."""
    context = EvaluationContext(
        slug="demo",
        timeframe="1m",
        symbol="BTC/USDT",
        side="buy",
        indicators=_FakeIndicators(),
        candle_index=2,
        state_store={},
    )

    values = await strategy_runtime._ema(context, [20, 50])

    assert values == {"ema_20": 30.0, "ema_50": 30.0}


@pytest.mark.asyncio
async def test_backtest_enters_on_next_candle_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Backtest(
        config={},
        symbol="BTC/USDT",
        strategy_slug="demo",
        timeframe="1m",
        start_date=datetime(2024, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 1, 1, 0, 3, tzinfo=UTC),
        take_profit_pct=1.0,
    )
    engine._candles = [
        OhlcvCandle(1_000, 100.0, 100.0, 100.0, 100.0, 1.0),
        OhlcvCandle(61_000, 105.0, 106.0, 104.0, 105.0, 1.0),
        OhlcvCandle(121_000, 106.0, 110.0, 105.0, 109.0, 1.0),
    ]

    async def fake_snapshot(slug: str) -> object:
        return object()

    async def fake_evaluate(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(matched=kwargs["candle_index"] == 0)

    monkeypatch.setattr(strategy_runtime, "_load_strategy_snapshot", fake_snapshot)
    monkeypatch.setattr(backtest_service, "evaluate_strategy_graph", fake_evaluate)

    result = await engine.run()

    assert result["trades"][0]["open_timestamp"] == 61_000
    assert result["trades"][0]["open_price"] == 105.0
    assert result["chart"]["markers"][0]["time"] == 61_000


@pytest.mark.asyncio
async def test_backtest_marks_still_open_trade_at_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Backtest(
        config={},
        symbol="BTC/USDT",
        strategy_slug="demo",
        timeframe="1m",
        start_date=datetime(2024, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 1, 1, 0, 3, tzinfo=UTC),
        take_profit_pct=50.0,
    )
    engine._candles = [_candle(0, 100.0), _candle(1, 100.0), _candle(2, 100.0)]

    async def fake_snapshot(slug: str) -> object:
        return object()

    async def fake_evaluate(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(matched=kwargs["candle_index"] == 0)

    monkeypatch.setattr(strategy_runtime, "_load_strategy_snapshot", fake_snapshot)
    monkeypatch.setattr(backtest_service, "evaluate_strategy_graph", fake_evaluate)

    result = await engine.run()

    assert result["trades"] == []
    assert result["stats"]["still_open_at_end"] is True


@pytest.mark.asyncio
async def test_sidestep_backtest_exits_on_bearish_and_waits_for_reentry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Backtest(
        config={},
        symbol="BTC/USDT",
        strategy_slug="ema20_swing",
        timeframe="1m",
        start_date=datetime(2024, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 1, 1, 0, 4, tzinfo=UTC),
        take_profit_pct=50.0,
        stop_loss_pct=50.0,
        trade_mode=TRADE_MODE_SIDESTEP,
        sidestep_bearish_strategy="ema_down",
        sidestep_reentry_strategy="ema20_swing_reverse",
    )
    engine._candles = [
        OhlcvCandle(1_000, 100.0, 100.0, 100.0, 100.0, 1.0),
        OhlcvCandle(61_000, 100.0, 101.0, 99.0, 100.0, 1.0),
        OhlcvCandle(121_000, 105.0, 106.0, 104.0, 105.0, 1.0),
        OhlcvCandle(181_000, 95.0, 96.0, 94.0, 95.0, 1.0),
    ]

    async def fake_snapshot(slug: str) -> object:
        return object()

    async def fake_evaluate(*args: Any, **kwargs: Any) -> Any:
        slug = args[0]
        candle_index = kwargs["candle_index"]
        matched = (
            slug == "ema20_swing_reverse"
            and candle_index == 0
            or slug == "ema_down"
            and candle_index == 1
        )
        return SimpleNamespace(matched=matched)

    monkeypatch.setattr(strategy_runtime, "_load_strategy_snapshot", fake_snapshot)
    monkeypatch.setattr(backtest_service, "evaluate_strategy_graph", fake_evaluate)

    result = await engine.run()

    assert result["trades"][0]["open_timestamp"] == 61_000
    assert result["trades"][0]["close_timestamp"] == 121_000
    assert result["trades"][0]["sell_reason"] == "sidestep_exit"
    assert result["trades"][0]["safety_orders_count"] == 0
    assert result["chart"]["markers"][0]["text"] == "RE-ENTRY"
    assert result["chart"]["markers"][1]["text"] == "SIDESTEP"
    assert result["stats"]["trade_mode"] == "sidestep"
    assert result["stats"]["sidestep_waiting_at_end"] is True


def test_sidestep_backtest_requires_sidestep_strategies() -> None:
    with pytest.raises(BacktestValidationError):
        Backtest(
            config={},
            symbol="BTC/USDT",
            strategy_slug="ema20_swing",
            timeframe="1m",
            start_date=datetime(2024, 1, 1, tzinfo=UTC),
            end_date=datetime(2024, 1, 1, 0, 4, tzinfo=UTC),
            trade_mode=TRADE_MODE_SIDESTEP,
            sidestep_bearish_strategy="ema_down",
        )


def test_candles_to_dataframe_empty_and_populated() -> None:
    assert candles_to_dataframe([]).empty
    df = candles_to_dataframe([_candle(0, 101.0), _candle(1, 102.0)])
    assert list(df["close"]) == [101.0, 102.0]


def test_dca_simulator_take_profit_uses_candle_high() -> None:
    sim = DcaSimulator(
        base_order_size=100.0,
        take_profit_pct=5.0,
        stop_loss_pct=5.0,
        max_safety_orders=0,
        fee=0.0,
    )
    trade = _make_state()
    closed = sim.evaluate(
        trade,
        OhlcvCandle(2_000, 100.0, 106.0, 99.0, 100.0, 1.0),
    )
    assert closed is not None
    assert closed.sell_reason == "take_profit"


def test_dca_simulator_stop_loss_requires_max_safety_orders() -> None:
    sim = DcaSimulator(
        base_order_size=100.0,
        take_profit_pct=5.0,
        stop_loss_pct=5.0,
        max_safety_orders=1,
        fee=0.0,
    )

    assert (
        sim.evaluate(_make_state(), OhlcvCandle(2_000, 100.0, 100.0, 90.0, 90.0, 1.0))
        is None
    )

    closed = sim.evaluate(
        _make_state(safety_orders_count=1),
        OhlcvCandle(2_000, 100.0, 100.0, 90.0, 90.0, 1.0),
    )
    assert closed is not None
    assert closed.sell_reason == "stop_loss"


def test_dca_simulator_tp_wins_same_candle_collision() -> None:
    sim = DcaSimulator(
        base_order_size=100.0,
        take_profit_pct=5.0,
        stop_loss_pct=5.0,
        max_safety_orders=0,
        fee=0.0,
    )

    closed = sim.evaluate(
        _make_state(),
        OhlcvCandle(2_000, 100.0, 106.0, 90.0, 95.0, 1.0),
    )

    assert closed is not None
    assert closed.sell_reason == "take_profit"


def test_dca_simulator_places_scaled_safety_order() -> None:
    sim = DcaSimulator(
        base_order_size=100.0,
        take_profit_pct=5.0,
        stop_loss_pct=5.0,
        max_safety_orders=2,
        safety_order_step_pct=10.0,
        step_scale=1.3,
        fee=0.0,
    )
    trade = _make_state()

    assert (
        sim.evaluate(trade, OhlcvCandle(2_000, 100.0, 100.0, 85.0, 89.0, 1.0)) is None
    )

    assert trade.safety_orders_count == 1
    assert trade.safety_orders[0]["cost"] == pytest.approx(100.0)
    assert calculate_safety_order_trigger_threshold(10.0, 1.3, 1) == pytest.approx(
        -23.0
    )
    max_deviation, _actual_deviation = calculate_static_deviations(1.3, 10.0, 1)
    assert calculate_safety_order_trigger_threshold(10.0, 1.3, 1) == pytest.approx(
        -max_deviation
    )


def test_validate_backtest_range_rejects_excessive_candles() -> None:
    start = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
    end = int(
        (datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=30)).timestamp() * 1000
    )

    with pytest.raises(BacktestValidationError):
        validate_backtest_range("1m", start, end)

    assert estimate_candle_count("1h", start, start + 3_600_000) == 2
    assert estimate_candle_count("1w", start, start + 7 * 86_400_000) == 2


@pytest.mark.asyncio
async def test_controller_validation_and_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConfigService:
        def snapshot(self) -> dict[str, Any]:
            return {"exchange": "binance"}

    class FakeConfig:
        @classmethod
        async def instance(cls) -> FakeConfigService:
            return FakeConfigService()

    class FakeBacktest:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def run(self) -> dict[str, Any]:
            assert self.kwargs["start_date"].tzinfo is not None
            assert self.kwargs["end_date"].tzinfo is not None
            assert self.kwargs["fee"] == 0.002
            assert self.kwargs["trade_mode"] == "sidestep"
            assert self.kwargs["sidestep_bearish_strategy"] == "ema_down"
            assert self.kwargs["sidestep_reentry_strategy"] == "ema20_swing_reverse"
            return {"ok": True}

    monkeypatch.setattr(backtest_controller, "Config", FakeConfig)
    monkeypatch.setattr(backtest_controller, "Backtest", FakeBacktest)

    missing = await backtest_controller._run_backtest({})
    assert missing.status_code == 400

    response = await backtest_controller._run_backtest(
        {
            "symbol": "BTC/USDT",
            "strategy_slug": "demo",
            "timeframe": "1h",
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": 1_704_070_800_000,
            "fee": 0.002,
            "trade_mode": "sidestep",
            "sidestep_bearish_strategy": "ema_down",
            "sidestep_reentry_strategy": "ema20_swing_reverse",
        }
    )

    assert response.status_code == 200
    assert _json(response) == {"ok": True}


@pytest.mark.asyncio
async def test_controller_returns_safe_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConfigService:
        def snapshot(self) -> dict[str, Any]:
            return {}

    class FakeConfig:
        @classmethod
        async def instance(cls) -> FakeConfigService:
            return FakeConfigService()

    class FailingBacktest:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run(self) -> dict[str, Any]:
            raise RuntimeError("secret stack detail")

    monkeypatch.setattr(backtest_controller, "Config", FakeConfig)
    monkeypatch.setattr(backtest_controller, "Backtest", FailingBacktest)

    response = await backtest_controller._run_backtest(
        {
            "symbol": "BTC/USDT",
            "strategy_slug": "demo",
            "timeframe": "1h",
            "start_date": "2024-01-01T00:00:00Z",
        }
    )

    body = _json(response)
    assert response.status_code == 500
    assert body["code"] == "backtest_failed"
    assert "secret" not in body["error"]


def test_backtest_route_uses_runtime_config_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Litestar route should not call the keyed Config.get API as a snapshot."""

    class FakeConfigService:
        def snapshot(self) -> dict[str, Any]:
            return {"exchange": "binance"}

    class FakeConfig:
        @classmethod
        async def instance(cls) -> FakeConfigService:
            return FakeConfigService()

    class FakeBacktest:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def run(self) -> dict[str, Any]:
            assert self.kwargs["config"] == {"exchange": "binance"}
            return {"ok": True}

    monkeypatch.setattr(backtest_controller, "Config", FakeConfig)
    monkeypatch.setattr(backtest_controller, "Backtest", FakeBacktest)

    app = Litestar(route_handlers=[backtest_controller.run_backtest])
    with TestClient(app=app, raise_server_exceptions=False) as client:
        response = client.post(
            "/backtest/run",
            json={
                "symbol": "BTC/USDT",
                "strategy_slug": "ema20_swing",
                "timeframe": "1h",
                "start_date": "2024-01-01T00:00:00Z",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_backtest_stats_use_shared_analytics_shape() -> None:
    rows = [
        {
            "symbol": "BTC/USDT",
            "deal_id": "1",
            "profit": 5.0,
            "profit_percent": 2.5,
            "cost": 100.0,
            "duration": "3600",
            "open_date": "2024-01-01T00:00:00+00:00",
            "close_date": "2024-01-01T01:00:00+00:00",
        }
    ]

    stats = compute_stats_from_trades(rows)

    assert set(stats) == {
        "summary",
        "heatmap_daily",
        "heatmap_weekly",
        "per_symbol",
        "duration_extremes",
        "drawdown",
        "distribution",
    }
    assert stats["summary"]["total_trades"] == 1
    assert stats["per_symbol"][0]["symbol"] == "BTC/USDT"


class _PagedExchange:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def milliseconds(self) -> int:
        return 600_000

    async def fetch_ohlcv(
        self,
        *,
        symbol: str,
        timeframe: str,
        since: int,
        limit: int,
    ) -> list[list[float]]:
        self.calls.append(since)
        if len(self.calls) == 1:
            return [
                [0, 1, 1, 1, 1, 1],
                [60_000, 1, 1, 1, 1, 1],
            ]
        return [
            [60_000, 1, 1, 1, 1, 1],
            [120_000, 1, 1, 1, 1, 1],
        ]


@pytest.mark.asyncio
async def test_batched_history_paces_pages_and_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = Exchange()
    exchange.exchange = _PagedExchange()
    sleeps: list[float] = []

    async def fake_ensure_exchange(_config: dict[str, object]) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(exchange, "_Exchange__ensure_exchange", fake_ensure_exchange)
    monkeypatch.setattr(
        exchange, "_Exchange__ensure_markets_loaded", fake_ensure_markets_loaded
    )
    monkeypatch.setattr(exchange, "_Exchange__resolve_symbol", lambda symbol: symbol)
    monkeypatch.setattr("service.exchange.asyncio.sleep", fake_sleep)

    candles = await exchange.get_history_for_symbol_batched(
        config={"exchange": "binance"},
        symbol="BTC/USDT",
        timeframe="1m",
        since=0,
        until=120_000,
        page_size=2,
        max_candles=10,
        page_delay=0.25,
    )

    assert [int(c[0]) for c in candles] == [0, 60_000, 120_000]
    assert sleeps == [0.25]
