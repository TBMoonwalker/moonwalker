import pandas as pd
import pytest
from strategies.ema20_swing import Strategy


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


def _install_fake_state_store(
    monkeypatch,
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

    monkeypatch.setattr(Strategy, "_load_persisted_state", fake_load)
    monkeypatch.setattr(Strategy, "_persist_previous_state", fake_persist)
    return persisted_store


def _install_fake_ema_builder(monkeypatch, ema_series_values: list[pd.Series]) -> None:
    def fake_build(_close_series: pd.Series) -> pd.Series:
        if not ema_series_values:
            raise AssertionError("No EMA20 test series left")
        return ema_series_values.pop(0)

    monkeypatch.setattr(Strategy, "_build_ema20_series", staticmethod(fake_build))


def test_ema20_swing_history_scan_returns_latest_qualified_state() -> None:
    close_series = pd.Series([10.0, 10.0, 10.4, 10.1, 10.8, 10.2, 11.0, 11.1])
    ema20_series = pd.Series([10.0, 10.0, 10.1, 10.0, 10.3, 10.2, 10.5, 10.4])

    latest_state = Strategy._find_latest_qualified_state_from_series(
        close_series,
        ema20_series,
    )

    assert latest_state == (11.0, 10.5)


def test_ema20_swing_candidate_rejects_missing_numbers() -> None:
    trigger_up, close_value, ema20_value = Strategy._evaluate_trigger_candidate(
        close_value=10.2,
        ema20_value=float("nan"),
        previous_ema20_value=10.0,
    )

    assert trigger_up is False
    assert close_value is None
    assert ema20_value is None


@pytest.mark.asyncio
async def test_ema20_swing_first_qualifying_candle_only_primes_state(
    monkeypatch,
) -> None:
    monkeypatch.setattr(Strategy, "_load_persisted_state", _no_op_load)
    monkeypatch.setattr(Strategy, "_persist_previous_state", _no_op_persist)
    monkeypatch.setattr(
        Strategy,
        "_bootstrap_previous_state_from_history",
        lambda self, _close_series: None,
    )
    _install_fake_ema_builder(
        monkeypatch,
        [_series(10.0, 10.3, 10.4)],
    )
    strategy = Strategy("4h")
    strategy.indicators = _StubIndicators(
        ema20_values=[10.4],
        close_series_values=[_series(9.8, 10.6, 10.7)],
    )

    result = await strategy.run("ERA/USDC", "buy")

    assert result is False
    assert strategy._previous_state_by_symbol["ERA/USDC"] == (10.6, 10.3)


@pytest.mark.asyncio
async def test_ema20_swing_returns_true_for_new_higher_closed_candle_signal(
    monkeypatch,
) -> None:
    monkeypatch.setattr(Strategy, "_load_persisted_state", _no_op_load)
    monkeypatch.setattr(Strategy, "_persist_previous_state", _no_op_persist)
    monkeypatch.setattr(
        Strategy,
        "_bootstrap_previous_state_from_history",
        lambda self, _close_series: None,
    )
    _install_fake_ema_builder(
        monkeypatch,
        [
            _series(10.0, 10.3, 10.4),
            _series(10.4, 10.7, 10.8),
        ],
    )
    strategy = Strategy("4h")
    strategy.indicators = _StubIndicators(
        ema20_values=[10.4, 10.8],
        close_series_values=[
            _series(9.8, 10.6, 10.7),
            _series(10.1, 11.0, 11.2),
        ],
    )

    first = await strategy.run("ERA/USDC", "buy")
    second = await strategy.run("ERA/USDC", "buy")

    assert first is False
    assert second is True


@pytest.mark.asyncio
async def test_ema20_swing_bootstraps_missing_state_without_trading(
    monkeypatch,
) -> None:
    persisted_store = _install_fake_state_store(monkeypatch)

    def fake_bootstrap(self, _close_series) -> tuple[float, float] | None:
        return (10.6, 10.3)

    monkeypatch.setattr(
        Strategy,
        "_bootstrap_previous_state_from_history",
        fake_bootstrap,
    )
    _install_fake_ema_builder(
        monkeypatch,
        [_series(10.4, 10.7, 10.8)],
    )

    strategy = Strategy("4h")
    strategy.indicators = _StubIndicators(
        ema20_values=[10.8],
        close_series_values=[_series(10.1, 11.0, 11.2)],
    )

    result = await strategy.run("ERA/USDC", "buy")

    assert result is False
    assert strategy._previous_state_by_symbol["ERA/USDC"] == (11.0, 10.7)
    assert persisted_store[("ERA/USDC", "4h")] == (11.0, 10.7)


@pytest.mark.asyncio
async def test_ema20_swing_load_persisted_state_returns_none_on_orm_error(
    monkeypatch,
) -> None:
    async def fake_get_or_none(*_args, **_kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        "strategies.ema20_swing.model.Ema20SwingState.get_or_none",
        fake_get_or_none,
    )

    strategy = Strategy("4h")

    assert await strategy._load_persisted_state("ERA/USDC") is None


@pytest.mark.asyncio
async def test_ema20_swing_persist_previous_state_swallows_write_errors(
    monkeypatch,
) -> None:
    async def fake_write_with_retry(*_args, **_kwargs):
        raise RuntimeError("sqlite busy")

    monkeypatch.setattr(
        "strategies.ema20_swing.run_sqlite_write_with_retry",
        fake_write_with_retry,
    )

    strategy = Strategy("4h")

    await strategy._persist_previous_state("ERA/USDC", 11.0, 10.7)


@pytest.mark.asyncio
async def test_ema20_swing_restart_does_not_retrigger_consumed_signal(
    monkeypatch,
) -> None:
    _install_fake_state_store(monkeypatch)
    monkeypatch.setattr(
        Strategy,
        "_bootstrap_previous_state_from_history",
        lambda self, _close_series: None,
    )
    _install_fake_ema_builder(
        monkeypatch,
        [
            _series(10.0, 10.3, 10.4),
            _series(10.0, 10.3, 10.4),
        ],
    )

    first_strategy = Strategy("4h")
    first_strategy.indicators = _StubIndicators(
        ema20_values=[10.4],
        close_series_values=[_series(9.8, 10.6, 10.7)],
    )
    assert await first_strategy.run("ERA/USDC", "buy") is False

    restarted_strategy = Strategy("4h")
    restarted_strategy.indicators = _StubIndicators(
        ema20_values=[10.4],
        close_series_values=[_series(9.8, 10.6, 10.7)],
    )

    assert await restarted_strategy.run("ERA/USDC", "buy") is False


@pytest.mark.asyncio
async def test_ema20_swing_restart_uses_persisted_state_for_next_signal(
    monkeypatch,
) -> None:
    persisted_store = _install_fake_state_store(monkeypatch)
    monkeypatch.setattr(
        Strategy,
        "_bootstrap_previous_state_from_history",
        lambda self, _close_series: None,
    )
    _install_fake_ema_builder(
        monkeypatch,
        [
            _series(10.0, 10.3, 10.4),
            _series(10.4, 10.7, 10.8),
        ],
    )

    first_strategy = Strategy("4h")
    first_strategy.indicators = _StubIndicators(
        ema20_values=[10.4],
        close_series_values=[_series(9.8, 10.6, 10.7)],
    )
    assert await first_strategy.run("ERA/USDC", "buy") is False
    assert persisted_store[("ERA/USDC", "4h")] == (10.6, 10.3)

    restarted_strategy = Strategy("4h")
    restarted_strategy.indicators = _StubIndicators(
        ema20_values=[10.8],
        close_series_values=[_series(10.1, 11.0, 11.2)],
    )

    assert await restarted_strategy.run("ERA/USDC", "buy") is True
    assert persisted_store[("ERA/USDC", "4h")] == (11.0, 10.7)
