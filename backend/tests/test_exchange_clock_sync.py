"""Regression tests for Bybit clock adjustment before market metadata reads."""

import asyncio
from unittest.mock import AsyncMock

import ccxt.async_support as ccxt
import pytest
from service.exchange_client_manager import ExchangeClientManager


class _Logger:
    def info(self, *_args: object) -> None:
        pass

    def warning(self, *_args: object) -> None:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("exchange_id", ["bybit", "bybiteu"])
@pytest.mark.parametrize("clock_offset", [-5164, 6000])
async def test_clock_adjusted_before_authenticated_currency_read(
    monkeypatch: pytest.MonkeyPatch, exchange_id: str, clock_offset: int
) -> None:
    manager = ExchangeClientManager(_Logger())
    exchange = await manager._init_exchange(
        {"exchange": exchange_id, "market": "spot", "dry_run": False}
    )
    manager.exchange = exchange
    server_time = 1791727279535
    events: list[str] = []
    monkeypatch.setattr(exchange, "milliseconds", lambda: server_time + clock_offset)

    async def fetch_time(_params: dict | None = None) -> int:
        events.append("time")
        return server_time

    async def fetch_currencies() -> dict:
        events.append("currencies")
        timestamp = exchange.nonce()
        if not server_time - 5000 <= timestamp < server_time + 1000:
            raise ccxt.InvalidNonce("bybiteu retCode 10002: timestamp outside window")
        return {}

    async def fetch_markets(_params: dict | None = None) -> list:
        events.append("markets")
        return []

    monkeypatch.setattr(exchange, "fetch_time", fetch_time)
    monkeypatch.setattr(exchange, "fetch_currencies", fetch_currencies)
    monkeypatch.setattr(exchange, "fetch_markets", fetch_markets)
    try:
        await manager.ensure_markets_loaded()
        assert events == ["time", "currencies", "markets"]
        assert exchange.options["adjustForTimeDifference"] is True
        assert exchange.options["recvWindow"] == 5000
        assert exchange.nonce() == server_time
        assert manager._markets_loaded is True
        await manager.ensure_markets_loaded()
        assert events == ["time", "currencies", "markets"]
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("exchange_id", ["bybit", "bybiteu"])
async def test_nonce_rejection_resyncs_and_retries_metadata_once(
    exchange_id: str,
) -> None:
    manager = ExchangeClientManager(_Logger())
    exchange = getattr(ccxt, exchange_id)()
    manager.exchange = exchange
    exchange.load_time_difference = AsyncMock(return_value=0)
    exchange.load_markets = AsyncMock(side_effect=[ccxt.InvalidNonce("10002"), {}])
    try:
        await manager.ensure_markets_loaded()
        assert exchange.load_markets.await_count == 2
        assert exchange.load_time_difference.await_count == 2
        assert manager._markets_loaded is True
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [ccxt.InvalidNonce("10002"), ccxt.RequestTimeout("slow")]
)
async def test_failed_refresh_never_marks_cache_fresh_or_retries_indefinitely(
    error: Exception,
) -> None:
    manager = ExchangeClientManager(_Logger())
    exchange = ccxt.bybiteu()
    manager.exchange = exchange
    exchange.load_time_difference = AsyncMock(return_value=0)
    exchange.load_markets = AsyncMock(side_effect=error)
    try:
        with pytest.raises(type(error)):
            await manager.ensure_markets_loaded()
        expected_calls = 2 if isinstance(error, ccxt.InvalidNonce) else 1
        assert exchange.load_markets.await_count == expected_calls
        assert exchange.load_time_difference.await_count == expected_calls
        assert manager._markets_loaded is False
        assert manager._markets_loaded_ts == 0
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_sync_failure_prevents_authenticated_metadata_request() -> None:
    manager = ExchangeClientManager(_Logger())
    exchange = ccxt.bybiteu()
    manager.exchange = exchange
    exchange.load_time_difference = AsyncMock(side_effect=ccxt.RequestTimeout("slow"))
    exchange.load_markets = AsyncMock()
    try:
        with pytest.raises(ccxt.RequestTimeout):
            await manager.ensure_markets_loaded()
        exchange.load_markets.assert_not_awaited()
        assert manager._markets_loaded is False
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_concurrent_expired_refreshes_share_one_clock_sync() -> None:
    manager = ExchangeClientManager(_Logger())
    exchange = ccxt.bybiteu()
    manager.exchange = exchange
    exchange.load_time_difference = AsyncMock(return_value=0)
    exchange.load_markets = AsyncMock(return_value={})
    try:
        await asyncio.gather(*(manager.ensure_markets_loaded() for _ in range(8)))
        assert exchange.load_markets.await_count == 1
        assert exchange.load_time_difference.await_count == 1
        manager._markets_loaded_ts -= manager.MARKETS_REFRESH_TTL_SECONDS + 1
        await manager.ensure_markets_loaded()
        assert exchange.load_time_difference.await_count == 2
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_other_exchange_nonce_failure_is_not_retried() -> None:
    manager = ExchangeClientManager(_Logger())
    exchange = ccxt.binance()
    manager.exchange = exchange
    exchange.load_time_difference = AsyncMock()
    exchange.load_markets = AsyncMock(side_effect=ccxt.InvalidNonce("other"))
    try:
        with pytest.raises(ccxt.InvalidNonce):
            await manager.ensure_markets_loaded()
        assert exchange.load_markets.await_count == 1
        exchange.load_time_difference.assert_not_awaited()
    finally:
        await manager.close()
