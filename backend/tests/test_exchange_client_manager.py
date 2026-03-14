"""Tests for exchange client manager."""

import pytest
from service.exchange_client_manager import ExchangeClientManager


class _DummyLogger:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass


class _DummyExchange:
    def __init__(self) -> None:
        self.close_calls = 0
        self.load_markets_calls = 0

    async def close(self) -> None:
        self.close_calls += 1

    async def load_markets(self) -> None:
        self.load_markets_calls += 1


@pytest.mark.asyncio
async def test_ensure_exchange_reuses_same_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ExchangeClientManager(_DummyLogger())
    exchange = _DummyExchange()

    async def fake_init_exchange(_config: dict[str, object]) -> _DummyExchange:
        return exchange

    monkeypatch.setattr(manager, "_init_exchange", fake_init_exchange)

    config = {
        "exchange": "binance",
        "key": "key",
        "secret": "secret",
        "market": "spot",
        "dry_run": True,
    }

    assert await manager.ensure_exchange(config) is True
    assert await manager.ensure_exchange(config) is False
    assert manager.exchange is exchange


@pytest.mark.asyncio
async def test_ensure_markets_loaded_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ExchangeClientManager(_DummyLogger())
    exchange = _DummyExchange()

    async def fake_init_exchange(_config: dict[str, object]) -> _DummyExchange:
        return exchange

    monkeypatch.setattr(manager, "_init_exchange", fake_init_exchange)
    await manager.ensure_exchange({"exchange": "binance"})

    await manager.ensure_markets_loaded()
    await manager.ensure_markets_loaded()

    assert exchange.load_markets_calls == 1


@pytest.mark.asyncio
async def test_ensure_markets_loaded_refreshes_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ExchangeClientManager(_DummyLogger())
    exchange = _DummyExchange()

    async def fake_init_exchange(_config: dict[str, object]) -> _DummyExchange:
        return exchange

    monkeypatch.setattr(manager, "_init_exchange", fake_init_exchange)
    await manager.ensure_exchange({"exchange": "binance"})

    await manager.ensure_markets_loaded()
    manager._markets_loaded_ts -= manager.MARKETS_REFRESH_TTL_SECONDS + 1
    await manager.ensure_markets_loaded()

    assert exchange.load_markets_calls == 2


@pytest.mark.asyncio
async def test_close_resets_client_state(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ExchangeClientManager(_DummyLogger())
    exchange = _DummyExchange()

    async def fake_init_exchange(_config: dict[str, object]) -> _DummyExchange:
        return exchange

    monkeypatch.setattr(manager, "_init_exchange", fake_init_exchange)
    await manager.ensure_exchange({"exchange": "binance"})
    await manager.ensure_markets_loaded()

    await manager.close()

    assert exchange.close_calls == 1
    assert manager.exchange is None
