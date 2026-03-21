"""Tests for exchange balance manager."""

import ccxt.async_support as ccxt
import pytest
from service.exchange import Exchange
from service.exchange_balance_manager import ExchangeBalanceManager


class _DummyLogger:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass


class _DummyExchange:
    def __init__(self) -> None:
        self.fetch_balance_calls = 0
        self.balance = {
            "BTC": {"free": "1.2345"},
            "free": {"USDT": "250.5"},
        }

    async def fetch_balance(self) -> dict[str, object]:
        self.fetch_balance_calls += 1
        return self.balance

    def amount_to_precision(self, _symbol: str, amount: float) -> str:
        return f"{amount:.3f}"


class _FlakyBalanceExchange(_DummyExchange):
    def __init__(self) -> None:
        super().__init__()
        self._fail_once = True

    async def fetch_balance(self) -> dict[str, object]:
        self.fetch_balance_calls += 1
        if self._fail_once:
            self._fail_once = False
            raise ccxt.NetworkError("502 Bad Gateway")
        return self.balance


def _resolve_symbol(symbol: str) -> str | None:
    mapping = {
        "BTC/USDT": "BTC/USDT",
        "BTC/USDT:USDT": "BTC/USDT:USDT",
    }
    return mapping.get(symbol, symbol if "/" in symbol else None)


@pytest.mark.asyncio
async def test_balance_snapshot_is_cached() -> None:
    exchange = _DummyExchange()
    manager = ExchangeBalanceManager(
        logger=_DummyLogger(),
        balance_cache_ttl_seconds=60.0,
        get_exchange=lambda: exchange,
        resolve_symbol=_resolve_symbol,
    )

    await manager.get_balance_snapshot()
    await manager.get_balance_snapshot()

    assert exchange.fetch_balance_calls == 1


@pytest.mark.asyncio
async def test_get_available_base_amount_uses_precision() -> None:
    exchange = _DummyExchange()
    manager = ExchangeBalanceManager(
        logger=_DummyLogger(),
        balance_cache_ttl_seconds=60.0,
        get_exchange=lambda: exchange,
        resolve_symbol=_resolve_symbol,
    )

    amount = await manager.get_available_base_amount("BTC/USDT")

    assert amount == 1.234


@pytest.mark.asyncio
async def test_get_free_quote_balance_reads_quote_asset() -> None:
    exchange = _DummyExchange()
    manager = ExchangeBalanceManager(
        logger=_DummyLogger(),
        balance_cache_ttl_seconds=60.0,
        get_exchange=lambda: exchange,
        resolve_symbol=_resolve_symbol,
    )

    balance = await manager.get_free_quote_balance("BTC/USDT")

    assert balance == 250.5


@pytest.mark.asyncio
async def test_reset_clears_cached_balance() -> None:
    exchange = _DummyExchange()
    manager = ExchangeBalanceManager(
        logger=_DummyLogger(),
        balance_cache_ttl_seconds=60.0,
        get_exchange=lambda: exchange,
        resolve_symbol=_resolve_symbol,
    )

    await manager.get_balance_snapshot()
    manager.reset()
    await manager.get_balance_snapshot()

    assert exchange.fetch_balance_calls == 2


@pytest.mark.asyncio
async def test_get_balance_snapshot_retries_transient_fetch_failure() -> None:
    exchange = _FlakyBalanceExchange()
    manager = ExchangeBalanceManager(
        logger=_DummyLogger(),
        balance_cache_ttl_seconds=60.0,
        get_exchange=lambda: exchange,
        resolve_symbol=_resolve_symbol,
    )

    balance = await manager.get_balance_snapshot()

    assert balance == exchange.balance
    assert exchange.fetch_balance_calls == 2


def test_exchange_accepts_custom_balance_cache_ttl() -> None:
    exchange = Exchange(balance_cache_ttl_seconds=5.0)

    assert exchange._balance_manager._balance_cache_ttl_seconds == 5.0
