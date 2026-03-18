import pandas as pd
import pytest
from strategies.ema_down import Strategy as EmaDownStrategy
from strategies.ema_low import Strategy as EmaLowStrategy


class _MissingEmaIndicators:
    async def calculate_ema(
        self, _symbol: str, _timeframe: str, _lengths: list[int]
    ) -> dict:
        return {}

    async def get_close_price(
        self, _symbol: str, _timeframe: str, _length: int
    ) -> pd.Series:
        return pd.Series([1.0, 2.0, 3.0])


class _ShortCloseIndicators:
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
        return pd.Series([9.5, 10.2])


@pytest.mark.asyncio
async def test_ema_low_returns_false_when_history_is_insufficient() -> None:
    strategy = EmaLowStrategy("4h")
    strategy.indicators = _ShortCloseIndicators()

    assert await strategy.run("NIGHT/USDC", "buy") is False


@pytest.mark.asyncio
async def test_ema_low_returns_false_when_ema_values_are_missing() -> None:
    strategy = EmaLowStrategy("4h")
    strategy.indicators = _MissingEmaIndicators()

    assert await strategy.run("NIGHT/USDC", "buy") is False


@pytest.mark.asyncio
async def test_ema_down_returns_false_when_ema_values_are_missing() -> None:
    strategy = EmaDownStrategy("4h")
    strategy.indicators = _MissingEmaIndicators()

    assert await strategy.run("NIGHT/USDC", "buy") is False
