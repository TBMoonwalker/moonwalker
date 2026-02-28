import pandas as pd
import pytest
from strategies.ema_swing import Strategy


class _StubIndicators:
    def __init__(self):
        self.close_calls = 0

    async def calculate_ema(self, _symbol: str, _timeframe: str, _lengths: list[int]):
        return {
            "ema_20": 10.0,
            "ema_50": 11.0,
            "ema_100": 12.0,
            "ema_200": 20.0,
        }

    async def get_close_price(self, _symbol: str, _timeframe: str, _length: int):
        self.close_calls += 1
        if self.close_calls == 1:
            # First swing-up with swing low = min(9.5, 9.0) = 9.0.
            return pd.Series([9.8, 9.0, 9.5, 10.2])
        # Second swing-up with higher swing low = min(9.9, 9.2) = 9.2.
        return pd.Series([10.0, 9.2, 9.9, 10.4])


@pytest.mark.asyncio
async def test_ema_swing_first_swing_only_primes_state():
    strategy = Strategy("4h")
    strategy.indicators = _StubIndicators()

    result = await strategy.run("ERA/USDC", "buy")

    assert result is False


@pytest.mark.asyncio
async def test_ema_swing_returns_true_when_new_swing_low_is_higher():
    strategy = Strategy("4h")
    strategy.indicators = _StubIndicators()

    first = await strategy.run("ERA/USDC", "buy")
    second = await strategy.run("ERA/USDC", "buy")

    assert first is False
    assert second is True
