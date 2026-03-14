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


class _ConfigurableExchange(_DummyExchange):
    def __init__(self, _params: dict[str, object]) -> None:
        super().__init__()
        self.demo_enabled = False
        self.sandbox_enabled = False

    def enableDemoTrading(self, enabled: bool) -> None:
        self.demo_enabled = enabled

    def set_sandbox_mode(self, enabled: bool) -> None:
        self.sandbox_enabled = enabled


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


@pytest.mark.asyncio
async def test_ensure_exchange_rebuilds_when_sandbox_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ExchangeClientManager(_DummyLogger())
    created: list[_DummyExchange] = []

    async def fake_init_exchange(_config: dict[str, object]) -> _DummyExchange:
        exchange = _DummyExchange()
        created.append(exchange)
        return exchange

    monkeypatch.setattr(manager, "_init_exchange", fake_init_exchange)

    assert (
        await manager.ensure_exchange(
            {"exchange": "binance", "dry_run": False, "sandbox": False}
        )
        is True
    )
    assert (
        await manager.ensure_exchange(
            {"exchange": "binance", "dry_run": False, "sandbox": True}
        )
        is True
    )

    assert len(created) == 2
    assert created[0].close_calls == 1


@pytest.mark.asyncio
async def test_build_exchange_config_ignores_sandbox_in_dry_run() -> None:
    manager = ExchangeClientManager(_DummyLogger())

    desired = manager.build_exchange_config(
        {
            "exchange": "binance",
            "dry_run": True,
            "sandbox": True,
        }
    )

    assert desired["dry_run"] is True
    assert desired["sandbox"] is False


@pytest.mark.asyncio
async def test_init_exchange_uses_demo_without_sandbox_when_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ExchangeClientManager(_DummyLogger())
    monkeypatch.setattr(
        "service.exchange_client_manager.ccxt.binance", _ConfigurableExchange
    )

    exchange = await manager._init_exchange(
        {
            "exchange": "binance",
            "market": "spot",
            "dry_run": True,
            "sandbox": True,
        }
    )

    assert exchange.demo_enabled is True
    assert exchange.sandbox_enabled is False


@pytest.mark.asyncio
async def test_init_exchange_uses_sandbox_only_when_not_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ExchangeClientManager(_DummyLogger())
    monkeypatch.setattr(
        "service.exchange_client_manager.ccxt.binance", _ConfigurableExchange
    )

    exchange = await manager._init_exchange(
        {
            "exchange": "binance",
            "market": "spot",
            "dry_run": False,
            "sandbox": True,
        }
    )

    assert exchange.demo_enabled is False
    assert exchange.sandbox_enabled is True
