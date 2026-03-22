import pandas as pd
import pytest
from strategies.ema_swing import Strategy


class _StubIndicators:
    def __init__(self):
        self.close_calls = 0

    async def calculate_ema(
        self, _symbol: str, _timeframe: str, _lengths: list[int]
    ) -> dict:
        return {
            "ema_20": 10.0,
            "ema_50": 11.0,
            "ema_100": 12.0,
            "ema_200": 20.0,
        }

    async def get_close_price(
        self, _symbol: str, _timeframe: str, _length: int
    ) -> pd.Series:
        self.close_calls += 1
        if self.close_calls == 1:
            # First swing-up with swing low = min(9.5, 9.0) = 9.0.
            return pd.Series([9.8, 9.0, 9.5, 10.2])
        # Second swing-up with higher swing low = min(9.9, 9.2) = 9.2.
        return pd.Series([10.0, 9.2, 9.9, 10.4])


async def _no_op_load(self, _symbol: str) -> float | None:
    return None


async def _no_op_persist(
    self,
    _symbol: str,
    _swing_low: float,
) -> None:
    return None


def _install_fake_state_store(monkeypatch) -> dict[tuple[str, str], float]:
    persisted_store: dict[tuple[str, str], float] = {}

    async def fake_load(self, symbol: str) -> float | None:
        return persisted_store.get((symbol, self.timeframe))

    async def fake_persist(self, symbol: str, swing_low: float) -> None:
        persisted_store[(symbol, self.timeframe)] = swing_low

    monkeypatch.setattr(Strategy, "_load_persisted_swing_low", fake_load)
    monkeypatch.setattr(Strategy, "_persist_previous_swing_low", fake_persist)
    return persisted_store


def test_ema_swing_history_scan_returns_latest_qualified_swing_low() -> None:
    close_series = pd.Series([11.0, 9.0, 10.2, 9.2, 9.4, 10.4])
    ema20_series = pd.Series([10.0] * len(close_series))
    ema50_series = pd.Series([11.0] * len(close_series))
    ema100_series = pd.Series([12.0] * len(close_series))
    ema200_series = pd.Series([20.0] * len(close_series))

    latest_swing_low = Strategy._find_latest_qualified_swing_low_from_series(
        close_series,
        ema20_series,
        ema50_series,
        ema100_series,
        ema200_series,
    )

    assert latest_swing_low == 9.2


def test_ema_swing_candidate_rejects_missing_numbers() -> None:
    trend_ok, swing_up, swing_low = Strategy._evaluate_swing_candidate(
        close_now=10.2,
        close_prev=float("nan"),
        close_prev2=9.0,
        ema20=10.0,
        ema50=11.0,
        ema100=12.0,
        ema200=20.0,
    )

    assert trend_ok is False
    assert swing_up is False
    assert swing_low is None


@pytest.mark.asyncio
async def test_ema_swing_first_swing_only_primes_state(monkeypatch) -> None:
    monkeypatch.setattr(Strategy, "_load_persisted_swing_low", _no_op_load)
    monkeypatch.setattr(Strategy, "_persist_previous_swing_low", _no_op_persist)
    strategy = Strategy("4h")
    strategy.indicators = _StubIndicators()

    result = await strategy.run("ERA/USDC", "buy")

    assert result is False


@pytest.mark.asyncio
async def test_ema_swing_returns_true_when_new_swing_low_is_higher(
    monkeypatch,
) -> None:
    monkeypatch.setattr(Strategy, "_load_persisted_swing_low", _no_op_load)
    monkeypatch.setattr(Strategy, "_persist_previous_swing_low", _no_op_persist)
    strategy = Strategy("4h")
    strategy.indicators = _StubIndicators()

    first = await strategy.run("ERA/USDC", "buy")
    second = await strategy.run("ERA/USDC", "buy")

    assert first is False
    assert second is True


@pytest.mark.asyncio
async def test_ema_swing_bootstraps_missing_state_without_trading(monkeypatch) -> None:
    persisted_store = _install_fake_state_store(monkeypatch)

    def fake_bootstrap(self, _close_series) -> float | None:
        return 9.0

    monkeypatch.setattr(
        Strategy,
        "_bootstrap_previous_swing_low_from_history",
        fake_bootstrap,
    )

    strategy = Strategy("4h")
    strategy.indicators = _StubIndicators()
    strategy.indicators.close_calls = 1

    result = await strategy.run("ERA/USDC", "buy")

    assert result is False
    assert strategy._previous_swing_low_by_symbol["ERA/USDC"] == 9.2
    assert persisted_store[("ERA/USDC", "4h")] == 9.2


@pytest.mark.asyncio
async def test_ema_swing_load_persisted_state_returns_none_on_orm_error(
    monkeypatch,
) -> None:
    async def fake_get_or_none(*_args, **_kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        "strategies.ema_swing.model.EmaSwingState.get_or_none",
        fake_get_or_none,
    )

    strategy = Strategy("4h")

    assert await strategy._load_persisted_swing_low("ERA/USDC") is None


@pytest.mark.asyncio
async def test_ema_swing_persist_previous_swing_low_swallows_write_errors(
    monkeypatch,
) -> None:
    async def fake_write_with_retry(*_args, **_kwargs):
        raise RuntimeError("sqlite busy")

    monkeypatch.setattr(
        "strategies.ema_swing.run_sqlite_write_with_retry",
        fake_write_with_retry,
    )

    strategy = Strategy("4h")

    await strategy._persist_previous_swing_low("ERA/USDC", 9.2)


@pytest.mark.asyncio
async def test_ema_swing_restart_does_not_retrigger_consumed_signal(
    monkeypatch,
) -> None:
    _install_fake_state_store(monkeypatch)

    first_strategy = Strategy("4h")
    first_strategy.indicators = _StubIndicators()
    assert await first_strategy.run("ERA/USDC", "buy") is False

    restarted_strategy = Strategy("4h")
    restarted_strategy.indicators = _StubIndicators()

    assert await restarted_strategy.run("ERA/USDC", "buy") is False


@pytest.mark.asyncio
async def test_ema_swing_restart_uses_persisted_state_for_next_higher_low(
    monkeypatch,
) -> None:
    persisted_store = _install_fake_state_store(monkeypatch)

    first_strategy = Strategy("4h")
    first_strategy.indicators = _StubIndicators()
    assert await first_strategy.run("ERA/USDC", "buy") is False
    assert persisted_store[("ERA/USDC", "4h")] == 9.0

    restarted_strategy = Strategy("4h")
    restarted_strategy.indicators = _StubIndicators()
    restarted_strategy.indicators.close_calls = 1

    assert await restarted_strategy.run("ERA/USDC", "buy") is True
    assert persisted_store[("ERA/USDC", "4h")] == 9.2
