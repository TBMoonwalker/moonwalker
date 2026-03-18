import ccxt.async_support as ccxt
import pytest
from service.ath import AthService


@pytest.mark.asyncio
async def test_fetch_ath_returns_zero_for_recoverable_exchange_error(
    monkeypatch,
) -> None:
    service = AthService()

    async def fail_recoverable(**_kwargs):
        raise ccxt.NetworkError("exchange unavailable")

    monkeypatch.setattr(
        service.exchange,
        "get_history_for_symbol",
        fail_recoverable,
    )

    result = await service._fetch_ath_from_exchange(
        symbol="BTC/USDT",
        config={},
        timeframe="4h",
        lookback_days=30,
    )

    assert result == 0.0


@pytest.mark.asyncio
async def test_fetch_ath_propagates_unexpected_programmer_errors(
    monkeypatch,
) -> None:
    service = AthService()

    async def fail_unexpected(**_kwargs):
        raise TypeError("unexpected candle parser bug")

    monkeypatch.setattr(
        service.exchange,
        "get_history_for_symbol",
        fail_unexpected,
    )

    with pytest.raises(TypeError, match="unexpected candle parser bug"):
        await service._fetch_ath_from_exchange(
            symbol="BTC/USDT",
            config={},
            timeframe="4h",
            lookback_days=30,
        )
