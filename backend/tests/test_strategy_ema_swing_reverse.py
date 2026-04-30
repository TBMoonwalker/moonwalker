import pandas as pd
import pytest
from strategies.ema_swing_reverse import Strategy


def _ema20_series(*tail: float) -> pd.Series:
    prefix_length = 24 - len(tail)
    return pd.Series([12.0] * prefix_length + list(tail))


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
    _swing_value: float,
    _ema20_value: float,
) -> None:
    return None


def _install_fake_state_store(
    monkeypatch,
) -> dict[tuple[str, str], tuple[float, float]]:
    persisted_store: dict[tuple[str, str], tuple[float, float]] = {}

    async def fake_load(self, symbol: str) -> tuple[float, float] | None:
        return persisted_store.get((symbol, self.timeframe))

    async def fake_persist(
        self,
        symbol: str,
        swing_value: float,
        ema20_value: float,
    ) -> None:
        persisted_store[(symbol, self.timeframe)] = (swing_value, ema20_value)

    monkeypatch.setattr(Strategy, "_load_persisted_state", fake_load)
    monkeypatch.setattr(Strategy, "_persist_previous_state", fake_persist)
    return persisted_store


def test_ema_swing_reverse_history_scan_returns_latest_qualified_swing_state() -> None:
    ema20_series = pd.Series([12.0, 12.0, 9.8, 10.0, 9.9, 9.6, 9.8, 9.7])

    latest_state = Strategy._find_latest_qualified_swing_state_from_series(ema20_series)

    assert latest_state == (9.8, 9.7)


def test_ema_swing_reverse_candidate_rejects_missing_numbers() -> None:
    swing_down, swing_value, ema20_value = Strategy._evaluate_swing_candidate(
        ema20_now=9.7,
        ema20_prev=float("nan"),
        ema20_prev2=9.6,
    )

    assert swing_down is False
    assert swing_value is None
    assert ema20_value is None


@pytest.mark.asyncio
async def test_ema_swing_reverse_first_swing_only_primes_state(monkeypatch) -> None:
    monkeypatch.setattr(Strategy, "_load_persisted_state", _no_op_load)
    monkeypatch.setattr(Strategy, "_persist_previous_state", _no_op_persist)
    monkeypatch.setattr(
        Strategy,
        "_build_ema20_series",
        staticmethod(lambda close_series: close_series),
    )
    strategy = Strategy("4h")
    strategy.indicators = _StubIndicators(
        ema20_values=[9.9],
        close_series_values=[_ema20_series(9.8, 10.0, 9.9)],
    )

    result = await strategy.run("ERA/USDC", "sell")

    assert result is False


@pytest.mark.asyncio
async def test_ema_swing_reverse_returns_true_when_ema20_and_swing_drop(
    monkeypatch,
) -> None:
    monkeypatch.setattr(Strategy, "_load_persisted_state", _no_op_load)
    monkeypatch.setattr(Strategy, "_persist_previous_state", _no_op_persist)
    monkeypatch.setattr(
        Strategy,
        "_build_ema20_series",
        staticmethod(lambda close_series: close_series),
    )
    strategy = Strategy("4h")
    strategy.indicators = _StubIndicators(
        ema20_values=[9.9, 9.7],
        close_series_values=[
            _ema20_series(9.8, 10.0, 9.9),
            _ema20_series(9.6, 9.8, 9.7),
        ],
    )

    first = await strategy.run("ERA/USDC", "sell")
    second = await strategy.run("ERA/USDC", "sell")

    assert first is False
    assert second is True


@pytest.mark.asyncio
async def test_ema_swing_reverse_bootstraps_missing_state_without_trading(
    monkeypatch,
) -> None:
    persisted_store = _install_fake_state_store(monkeypatch)

    def fake_bootstrap(self, _close_series) -> tuple[float, float] | None:
        return (10.0, 9.9)

    monkeypatch.setattr(
        Strategy,
        "_bootstrap_previous_state_from_history",
        fake_bootstrap,
    )
    monkeypatch.setattr(
        Strategy,
        "_build_ema20_series",
        staticmethod(lambda close_series: close_series),
    )

    strategy = Strategy("4h")
    strategy.indicators = _StubIndicators(
        ema20_values=[9.7],
        close_series_values=[_ema20_series(9.6, 9.8, 9.7)],
    )

    result = await strategy.run("ERA/USDC", "sell")

    assert result is False
    assert strategy._previous_state_by_symbol["ERA/USDC"] == (9.8, 9.7)
    assert persisted_store[("ERA/USDC", "4h")] == (9.8, 9.7)


@pytest.mark.asyncio
async def test_ema_swing_reverse_load_persisted_state_returns_none_on_orm_error(
    monkeypatch,
) -> None:
    async def fake_get_or_none(*_args, **_kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        "strategies.ema_swing_reverse.model.EmaSwingReverseState.get_or_none",
        fake_get_or_none,
    )

    strategy = Strategy("4h")

    assert await strategy._load_persisted_state("ERA/USDC") is None


@pytest.mark.asyncio
async def test_ema_swing_reverse_persist_previous_state_swallows_write_errors(
    monkeypatch,
) -> None:
    async def fake_write_with_retry(*_args, **_kwargs):
        raise RuntimeError("sqlite busy")

    monkeypatch.setattr(
        "strategies.ema_swing_reverse.run_sqlite_write_with_retry",
        fake_write_with_retry,
    )

    strategy = Strategy("4h")

    await strategy._persist_previous_state("ERA/USDC", 9.8, 9.7)


@pytest.mark.asyncio
async def test_ema_swing_reverse_restart_does_not_retrigger_consumed_signal(
    monkeypatch,
) -> None:
    _install_fake_state_store(monkeypatch)
    monkeypatch.setattr(
        Strategy,
        "_build_ema20_series",
        staticmethod(lambda close_series: close_series),
    )

    first_strategy = Strategy("4h")
    first_strategy.indicators = _StubIndicators(
        ema20_values=[9.9],
        close_series_values=[_ema20_series(9.8, 10.0, 9.9)],
    )
    assert await first_strategy.run("ERA/USDC", "sell") is False

    restarted_strategy = Strategy("4h")
    restarted_strategy.indicators = _StubIndicators(
        ema20_values=[9.9],
        close_series_values=[_ema20_series(9.8, 10.0, 9.9)],
    )

    assert await restarted_strategy.run("ERA/USDC", "sell") is False


@pytest.mark.asyncio
async def test_ema_swing_reverse_restart_uses_persisted_state_for_next_lower_swing(
    monkeypatch,
) -> None:
    persisted_store = _install_fake_state_store(monkeypatch)
    monkeypatch.setattr(
        Strategy,
        "_build_ema20_series",
        staticmethod(lambda close_series: close_series),
    )

    first_strategy = Strategy("4h")
    first_strategy.indicators = _StubIndicators(
        ema20_values=[9.9],
        close_series_values=[_ema20_series(9.8, 10.0, 9.9)],
    )
    assert await first_strategy.run("ERA/USDC", "sell") is False
    assert persisted_store[("ERA/USDC", "4h")] == (10.0, 9.9)

    restarted_strategy = Strategy("4h")
    restarted_strategy.indicators = _StubIndicators(
        ema20_values=[9.7],
        close_series_values=[_ema20_series(9.6, 9.8, 9.7)],
    )

    assert await restarted_strategy.run("ERA/USDC", "sell") is True
    assert persisted_store[("ERA/USDC", "4h")] == (9.8, 9.7)
