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
