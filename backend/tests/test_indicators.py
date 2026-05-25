import pandas as pd
import pytest
from service.indicators import Indicators
from tortoise.exceptions import BaseORMException


@pytest.mark.asyncio
async def test_btc_pulse_fails_open_when_orm_read_fails(monkeypatch) -> None:
    indicator = Indicators()

    async def raise_orm_error(*_args, **_kwargs):
        raise BaseORMException("sqlite busy during BTC pulse")

    monkeypatch.setattr(indicator.data, "get_data_for_pair", raise_orm_error)

    assert await indicator.calculate_btc_pulse("USDC", "1m") is True


class _IndicatorData:
    def __init__(self) -> None:
        self.frame = pd.DataFrame(
            {
                "close": [
                    100.0 + ((index % 11) - 5) + index * 0.05 for index in range(250)
                ],
                "high": [102.0 + index * 0.05 for index in range(250)],
                "low": [98.0 + index * 0.05 for index in range(250)],
                "volume": [10.0 for _ in range(250)],
            }
        )

    async def get_latest_timestamp_for_pair(self, symbol: str) -> float:
        return 250.0

    async def get_data_for_pair_by_days(self, symbol: str, days: int):
        return self.frame

    async def get_data_for_pair(self, symbol: str, timerange: str, length: int):
        return self.frame

    def resample_data(self, frame, timerange: str):
        return frame


@pytest.mark.asyncio
async def test_talib_bollinger_rsi_and_macd_indicators_return_values() -> None:
    indicators = Indicators(data=_IndicatorData())

    bollinger = await indicators.calculate_bollinger_bands("BTC/USDC", "4h")
    rsi = await indicators.calculate_rsi("BTC/USDC", "4h", 14)
    macd = await indicators.calculate_macd("BTC/USDC", "4h")
    lows = await indicators.get_low_price("BTC/USDC", "4h", 20)
    highs = await indicators.get_high_price("BTC/USDC", "4h", 20)

    assert bollinger is not None
    assert bollinger["upper"] > bollinger["middle"] > bollinger["lower"]
    assert bollinger["bandwidth"] > 0
    assert rsi is not None
    assert 0 <= rsi <= 100
    assert macd is not None
    assert set(macd) == {"macd", "signal", "histogram"}
    assert lows.iloc[-1] == pytest.approx(_IndicatorData().frame["low"].iloc[-1])
    assert highs.iloc[-1] == pytest.approx(_IndicatorData().frame["high"].iloc[-1])
