import pandas as pd
import pytest
from service.strategy_ema20_swing_core import EMA20_REQUIRED_CLOSED_CANDLES
from strategies.ema20_swing import Strategy as BullishStrategy
from strategies.ema20_swing_reverse import Strategy as BearishStrategy


def _series(*tail: float, fill: float = 12.0) -> pd.Series:
    prefix_length = 24 - len(tail)
    return pd.Series([fill] * prefix_length + list(tail))


class _StubIndicators:
    def __init__(
        self,
        ema20_values: list[float],
        close_series_values: list[pd.Series],
    ) -> None:
        self._ema20_values = ema20_values
        self._close_series_values = close_series_values
        self.close_calls = 0
        self.ema_calls = 0

    async def calculate_ema(
        self,
        _symbol: str,
        _timeframe: str,
        _lengths: list[int],
    ) -> dict:
        index = min(self.ema_calls, len(self._ema20_values) - 1)
        self.ema_calls += 1
        return {"ema_20": self._ema20_values[index]}

    async def get_close_price(
        self,
        _symbol: str,
        _timeframe: str,
        _length: int,
    ) -> pd.Series:
        index = min(self.close_calls, len(self._close_series_values) - 1)
        self.close_calls += 1
        return self._close_series_values[index]


async def _no_op_load(self, _symbol: str) -> tuple[float, float] | None:
    return None


async def _no_op_persist(
    self,
    _symbol: str,
    _close_value: float,
    _ema20_value: float,
) -> None:
    return None


VARIANTS = (
    {
        "label": "bullish",
        "strategy_cls": BullishStrategy,
        "action": "buy",
        "latest_state": (11.0, 10.5),
        "history_close": pd.Series([10.0, 10.0, 10.4, 10.1, 10.8, 10.2, 11.0, 11.1]),
        "history_ema": pd.Series([10.0, 10.0, 10.1, 10.0, 10.3, 10.2, 10.5, 10.4]),
        "candidate_kwargs": {
            "close_value": 10.2,
            "ema20_value": float("nan"),
            "previous_ema20_value": 10.0,
        },
        "first_run_ema_series": [_series(10.0, 10.3, 10.4)],
        "first_run_ema_values": [10.4],
        "first_run_close_series": [_series(9.8, 10.6, 10.7)],
        "first_run_state": (10.7, 10.4),
        "next_signal_ema_series": [
            _series(10.0, 10.3, 10.4),
            _series(10.4, 10.7, 10.8),
        ],
        "next_signal_ema_values": [10.4, 10.8],
        "next_signal_close_series": [
            _series(9.8, 10.6, 10.7),
            _series(10.1, 11.0, 11.2),
        ],
        "bootstrap_state": (10.6, 10.3),
        "bootstrapped_state": (11.2, 10.8),
        "restart_first_series": _series(10.0, 10.3, 10.4),
        "restart_first_ema": 10.4,
        "restart_first_close": _series(9.8, 10.6, 10.7),
        "restart_next_series": _series(10.4, 10.7, 10.8),
        "restart_next_ema": 10.8,
        "restart_next_close": _series(10.1, 11.0, 11.2),
        "boundary_persisted_state": (79000.0, 80450.0),
        "boundary_ema_series": [_series(80640.0, 80650.0, 80693.0, fill=79000.0)],
        "boundary_ema_values": [80693.0],
        "boundary_close_series": [_series(80580.0, 80620.0, 80867.0, fill=79000.0)],
        "boundary_state": (80867.0, 80693.0),
        "trend_key": "ema20_rising",
        "position_key": "closed_above_ema20",
        "model_target": "strategies.ema20_swing.model.Ema20SwingState.get_or_none",
    },
    {
        "label": "bearish",
        "strategy_cls": BearishStrategy,
        "action": "sell",
        "latest_state": (9.2, 9.4),
        "history_close": pd.Series([10.0, 10.0, 9.7, 10.1, 9.5, 10.2, 9.2, 9.1]),
        "history_ema": pd.Series([10.0, 10.0, 9.9, 10.0, 9.7, 9.8, 9.4, 9.5]),
        "candidate_kwargs": {
            "close_value": 9.7,
            "ema20_value": float("nan"),
            "previous_ema20_value": 10.0,
        },
        "first_run_ema_series": [_series(10.0, 9.7, 9.6)],
        "first_run_ema_values": [9.6],
        "first_run_close_series": [_series(10.2, 9.4, 9.3)],
        "first_run_state": (9.3, 9.6),
        "next_signal_ema_series": [
            _series(10.0, 9.7, 9.6),
            _series(9.8, 9.4, 9.3),
        ],
        "next_signal_ema_values": [9.6, 9.3],
        "next_signal_close_series": [
            _series(10.2, 9.4, 9.3),
            _series(9.9, 9.0, 8.9),
        ],
        "bootstrap_state": (9.4, 9.7),
        "bootstrapped_state": (8.9, 9.3),
        "restart_first_series": _series(10.0, 9.7, 9.6),
        "restart_first_ema": 9.6,
        "restart_first_close": _series(10.2, 9.4, 9.3),
        "restart_next_series": _series(9.8, 9.4, 9.3),
        "restart_next_ema": 9.3,
        "restart_next_close": _series(9.9, 9.0, 8.9),
        "boundary_persisted_state": (76334.49, 76536.88156304843),
        "boundary_ema_series": [
            _series(80780.0, 80750.49977511245, 80693.0, fill=82000.0)
        ],
        "boundary_ema_values": [80693.0],
        "boundary_close_series": [_series(81020.0, 80864.61, 79867.0, fill=82000.0)],
        "boundary_state": (79867.0, 80693.0),
        "trend_key": "ema20_falling",
        "position_key": "closed_below_ema20",
        "model_target": "strategies.ema20_swing_reverse.model.EmaSwingReverseState.get_or_none",
    },
)


def test_ema20_swing_pair_uses_distinct_state_namespaces() -> None:
    bullish_strategy = BullishStrategy("4h")
    bearish_strategy = BearishStrategy("4h")

    assert bullish_strategy.state_model is not bearish_strategy.state_model
    assert bullish_strategy._state_timeframe != bearish_strategy._state_timeframe


def _install_fake_state_store(
    monkeypatch: pytest.MonkeyPatch,
    strategy_cls: type,
) -> dict[tuple[str, str], tuple[float, float]]:
    persisted_store: dict[tuple[str, str], tuple[float, float]] = {}

    async def fake_load(self, symbol: str) -> tuple[float, float] | None:
        return persisted_store.get((symbol, self.timeframe))

    async def fake_persist(
        self,
        symbol: str,
        close_value: float,
        ema20_value: float,
    ) -> None:
        persisted_store[(symbol, self.timeframe)] = (close_value, ema20_value)

    monkeypatch.setattr(strategy_cls, "_load_persisted_state", fake_load)
    monkeypatch.setattr(strategy_cls, "_persist_previous_state", fake_persist)
    return persisted_store


def _install_fake_ema_builder(
    monkeypatch: pytest.MonkeyPatch,
    strategy_cls: type,
    ema_series_values: list[pd.Series],
) -> None:
    def fake_build(_close_series: pd.Series) -> pd.Series:
        if not ema_series_values:
            raise AssertionError("No EMA20 test series left")
        return ema_series_values.pop(0)

    monkeypatch.setattr(strategy_cls, "_build_ema20_series", staticmethod(fake_build))


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda variant: variant["label"])
def test_ema20_swing_pair_history_scan_returns_latest_qualified_state(variant) -> None:
    strategy = variant["strategy_cls"]("4h")

    latest_state = strategy._find_latest_qualified_state_from_series(
        variant["history_close"],
        variant["history_ema"],
    )

    assert latest_state == variant["latest_state"]


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda variant: variant["label"])
def test_ema20_swing_pair_candidate_rejects_missing_numbers(variant) -> None:
    strategy = variant["strategy_cls"]("4h")

    trigger, close_value, ema20_value = strategy._evaluate_trigger_candidate(
        **variant["candidate_kwargs"],
    )

    assert trigger is False
    assert close_value is None
    assert ema20_value is None


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda variant: variant["label"])
@pytest.mark.asyncio
async def test_ema20_swing_pair_first_signal_only_primes_state(
    monkeypatch: pytest.MonkeyPatch,
    variant,
) -> None:
    strategy_cls = variant["strategy_cls"]
    monkeypatch.setattr(strategy_cls, "_load_persisted_state", _no_op_load)
    monkeypatch.setattr(strategy_cls, "_persist_previous_state", _no_op_persist)
    monkeypatch.setattr(
        strategy_cls,
        "_bootstrap_previous_state_from_history",
        lambda self, _close_series: None,
    )
    _install_fake_ema_builder(
        monkeypatch,
        strategy_cls,
        list(variant["first_run_ema_series"]),
    )
    strategy = strategy_cls("4h")
    strategy.indicators = _StubIndicators(
        ema20_values=list(variant["first_run_ema_values"]),
        close_series_values=list(variant["first_run_close_series"]),
    )

    result = await strategy.run("ERA/USDC", variant["action"])

    assert result is False
    assert strategy._previous_state_by_symbol["ERA/USDC"] == variant["first_run_state"]


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda variant: variant["label"])
@pytest.mark.asyncio
async def test_ema20_swing_pair_logs_skip_reason_for_insufficient_candles(
    variant,
) -> None:
    strategy = variant["strategy_cls"]("4h")
    insufficient_series = pd.Series([10.0, 10.1, 10.2])
    strategy.indicators = _StubIndicators(
        ema20_values=[variant["first_run_ema_values"][0]],
        close_series_values=[insufficient_series],
    )

    result = await strategy.run("ERA/USDC", variant["action"])

    assert result is False
    assert strategy._last_log_by_symbol["ERA/USDC"] == {
        "symbol": "ERA/USDC",
        "reason": "insufficient_closed_candles",
        "ema20(current)": variant["first_run_ema_values"][0],
        "available_closed_candles": 3,
        "required_closed_candles": EMA20_REQUIRED_CLOSED_CANDLES,
        "creating_order": False,
    }


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda variant: variant["label"])
@pytest.mark.asyncio
async def test_ema20_swing_pair_returns_true_for_new_signal(
    monkeypatch: pytest.MonkeyPatch,
    variant,
) -> None:
    strategy_cls = variant["strategy_cls"]
    monkeypatch.setattr(strategy_cls, "_load_persisted_state", _no_op_load)
    monkeypatch.setattr(strategy_cls, "_persist_previous_state", _no_op_persist)
    monkeypatch.setattr(
        strategy_cls,
        "_bootstrap_previous_state_from_history",
        lambda self, _close_series: None,
    )
    _install_fake_ema_builder(
        monkeypatch,
        strategy_cls,
        list(variant["next_signal_ema_series"]),
    )
    strategy = strategy_cls("4h")
    strategy.indicators = _StubIndicators(
        ema20_values=list(variant["next_signal_ema_values"]),
        close_series_values=list(variant["next_signal_close_series"]),
    )

    first = await strategy.run("ERA/USDC", variant["action"])
    second = await strategy.run("ERA/USDC", variant["action"])

    assert first is False
    assert second is True


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda variant: variant["label"])
@pytest.mark.asyncio
async def test_ema20_swing_pair_bootstraps_missing_state_without_trading(
    monkeypatch: pytest.MonkeyPatch,
    variant,
) -> None:
    strategy_cls = variant["strategy_cls"]
    persisted_store = _install_fake_state_store(monkeypatch, strategy_cls)

    def fake_bootstrap(self, _close_series) -> tuple[float, float] | None:
        return variant["bootstrap_state"]

    monkeypatch.setattr(
        strategy_cls,
        "_bootstrap_previous_state_from_history",
        fake_bootstrap,
    )
    _install_fake_ema_builder(
        monkeypatch,
        strategy_cls,
        [variant["next_signal_ema_series"][-1]],
    )

    strategy = strategy_cls("4h")
    strategy.indicators = _StubIndicators(
        ema20_values=[variant["next_signal_ema_values"][-1]],
        close_series_values=[variant["next_signal_close_series"][-1]],
    )

    result = await strategy.run("ERA/USDC", variant["action"])

    assert result is False
    assert (
        strategy._previous_state_by_symbol["ERA/USDC"] == variant["bootstrapped_state"]
    )
    assert persisted_store[("ERA/USDC", "4h")] == variant["bootstrapped_state"]


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda variant: variant["label"])
@pytest.mark.asyncio
async def test_ema20_swing_pair_restart_uses_persisted_state_without_cross_talk(
    monkeypatch: pytest.MonkeyPatch,
    variant,
) -> None:
    strategy_cls = variant["strategy_cls"]
    persisted_store = _install_fake_state_store(monkeypatch, strategy_cls)
    monkeypatch.setattr(
        strategy_cls,
        "_bootstrap_previous_state_from_history",
        lambda self, _close_series: None,
    )
    _install_fake_ema_builder(
        monkeypatch,
        strategy_cls,
        [
            variant["restart_first_series"],
            variant["restart_next_series"],
        ],
    )

    first_strategy = strategy_cls("4h")
    first_strategy.indicators = _StubIndicators(
        ema20_values=[variant["restart_first_ema"]],
        close_series_values=[variant["restart_first_close"]],
    )
    assert await first_strategy.run("ERA/USDC", variant["action"]) is False
    assert persisted_store[("ERA/USDC", "4h")] == variant["first_run_state"]

    restarted_strategy = strategy_cls("4h")
    restarted_strategy.indicators = _StubIndicators(
        ema20_values=[variant["restart_next_ema"]],
        close_series_values=[variant["restart_next_close"]],
    )

    assert await restarted_strategy.run("ERA/USDC", variant["action"]) is True
    assert persisted_store[("ERA/USDC", "4h")] == variant["bootstrapped_state"]


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda variant: variant["label"])
@pytest.mark.asyncio
async def test_ema20_swing_pair_load_persisted_state_returns_none_on_orm_error(
    monkeypatch: pytest.MonkeyPatch,
    variant,
) -> None:
    async def fake_get_or_none(*_args, **_kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(variant["model_target"], fake_get_or_none)

    strategy = variant["strategy_cls"]("4h")

    assert await strategy._load_persisted_state("ERA/USDC") is None


@pytest.mark.asyncio
async def test_ema20_swing_pair_persist_previous_state_swallows_write_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_write_with_retry(*_args, **_kwargs):
        raise RuntimeError("sqlite busy")

    monkeypatch.setattr(
        "service.strategy_ema20_swing_core.run_sqlite_write_with_retry",
        fake_write_with_retry,
    )

    await BullishStrategy("4h")._persist_previous_state("ERA/USDC", 11.0, 10.7)
    await BearishStrategy("4h")._persist_previous_state("ERA/USDC", 9.0, 9.4)


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda variant: variant["label"])
@pytest.mark.asyncio
async def test_ema20_swing_pair_uses_latest_closed_candle_at_boundary(
    monkeypatch: pytest.MonkeyPatch,
    variant,
) -> None:
    strategy_cls = variant["strategy_cls"]
    persisted_store = _install_fake_state_store(monkeypatch, strategy_cls)
    persisted_store[("BTC/USDC", "4h")] = variant["boundary_persisted_state"]
    monkeypatch.setattr(
        strategy_cls,
        "_bootstrap_previous_state_from_history",
        lambda self, _close_series: None,
    )
    _install_fake_ema_builder(
        monkeypatch,
        strategy_cls,
        list(variant["boundary_ema_series"]),
    )

    strategy = strategy_cls("4h")
    strategy.indicators = _StubIndicators(
        ema20_values=list(variant["boundary_ema_values"]),
        close_series_values=list(variant["boundary_close_series"]),
    )

    result = await strategy.run("BTC/USDC", variant["action"])

    assert result is True
    assert strategy._previous_state_by_symbol["BTC/USDC"] == variant["boundary_state"]
    assert strategy._last_log_by_symbol["BTC/USDC"]["creating_order"] is True
    assert strategy._last_log_by_symbol["BTC/USDC"][variant["position_key"]] is True
    assert strategy._last_log_by_symbol["BTC/USDC"][variant["trend_key"]] is True
