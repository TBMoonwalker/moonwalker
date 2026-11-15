"""Tests for bounded historical OHLCV fetches."""

import asyncio

import ccxt.async_support as ccxt
import pytest
from service.exchange import Exchange


class _DummyHistoryExchange:
    def __init__(self) -> None:
        self.fetch_calls: list[tuple[str, str, int, int]] = []

    def parse_timeframe(self, timeframe: str) -> int:
        assert timeframe == "1m"
        return 60

    def milliseconds(self) -> int:
        return 600_000

    async def fetch_ohlcv(
        self,
        *,
        symbol: str,
        timeframe: str,
        since: int,
        limit: int,
        params: dict[str, int],
    ) -> list[list[float]]:
        assert params == {"until": 120_000}
        self.fetch_calls.append((symbol, timeframe, since, limit))
        return [
            [0, 1.0, 2.0, 0.5, 1.5, 10.0],
            [60_000, 1.5, 2.5, 1.0, 2.0, 10.0],
            [120_000, 2.0, 3.0, 1.5, 2.5, 10.0],
            [180_000, 2.5, 3.5, 2.0, 3.0, 10.0],
        ]


class _FlakyHistoryExchange:
    """Fail the first N pages with a network error, then serve candles."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def parse_timeframe(self, timeframe: str) -> int:
        return 60

    def milliseconds(self) -> int:
        return 600_000

    async def fetch_ohlcv(
        self,
        *,
        symbol: str,
        timeframe: str,
        since: int,
        limit: int,
        **kwargs: object,
    ) -> list[list[float]]:
        self.calls += 1
        if self.calls <= self.failures:
            raise ccxt.NetworkError("synthetic network failure")
        return [
            [0, 1.0, 2.0, 0.5, 1.5, 10.0],
            [60_000, 1.5, 2.5, 1.0, 2.0, 10.0],
            [120_000, 2.0, 3.0, 1.5, 2.5, 10.0],
        ]


def _install_history_primitives(
    exchange: Exchange,
    dummy: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange.exchange = dummy

    async def fake_ensure_exchange(_config: dict[str, object]) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    monkeypatch.setattr(exchange, "_ensure_exchange", fake_ensure_exchange)
    monkeypatch.setattr(exchange, "_ensure_markets_loaded", fake_ensure_markets_loaded)
    monkeypatch.setattr(exchange, "_resolve_symbol", lambda symbol: symbol)


@pytest.mark.asyncio
async def test_get_history_for_symbol_respects_until_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = Exchange()
    _install_history_primitives(exchange, _DummyHistoryExchange(), monkeypatch)

    candles = await exchange.get_history_for_symbol(
        config={"exchange": "binance"},
        symbol="BTC/USDT",
        timeframe="1m",
        limit=1000,
        since=0,
        until=120_000,
    )

    assert [int(candle[0]) for candle in candles] == [0, 60_000, 120_000]
    assert exchange.exchange.fetch_calls == [("BTC/USDT", "1m", 0, 1000)]


@pytest.mark.asyncio
async def test_history_page_backoff_stops_at_error_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = Exchange()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    for count in range(1, Exchange.HISTORY_MAX_CONSECUTIVE_ERRORS):
        assert await exchange._history_page_backoff(
            fetch_kind="history",
            symbol="BTC/USDT",
            consecutive_errors=count,
            backoff_seconds=lambda _count: 1.0,
        )
    assert not await exchange._history_page_backoff(
        fetch_kind="history",
        symbol="BTC/USDT",
        consecutive_errors=Exchange.HISTORY_MAX_CONSECUTIVE_ERRORS,
        backoff_seconds=lambda _count: 1.0,
    )
    assert sleeps == [1.0] * (Exchange.HISTORY_MAX_CONSECUTIVE_ERRORS - 1)


@pytest.mark.asyncio
async def test_get_history_for_symbol_recovers_within_error_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = Exchange()
    dummy = _FlakyHistoryExchange(failures=2)
    _install_history_primitives(exchange, dummy, monkeypatch)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    candles = await exchange.get_history_for_symbol(
        config={"exchange": "binance"},
        symbol="BTC/USDT",
        timeframe="1m",
        limit=1000,
        since=0,
        until=120_000,
    )

    assert [int(candle[0]) for candle in candles] == [0, 60_000, 120_000]
    assert dummy.calls == 3
    assert sleeps == [
        Exchange.HISTORY_RETRY_SLEEP_SECONDS,
        Exchange.HISTORY_RETRY_SLEEP_SECONDS,
    ]


@pytest.mark.asyncio
async def test_get_history_for_symbol_batched_stops_at_error_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = Exchange()
    dummy = _FlakyHistoryExchange(failures=Exchange.HISTORY_MAX_CONSECUTIVE_ERRORS)
    _install_history_primitives(exchange, dummy, monkeypatch)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    page_delay = 0.5

    candles = await exchange.get_history_for_symbol_batched(
        config={"exchange": "binance"},
        symbol="BTC/USDT",
        timeframe="1m",
        since=0,
        until=120_000,
        page_size=1000,
        max_candles=20_000,
        page_delay=page_delay,
    )

    assert candles == []
    assert dummy.calls == Exchange.HISTORY_MAX_CONSECUTIVE_ERRORS
    assert sleeps == [
        page_delay * (2 ** (count - 1))
        for count in range(1, Exchange.HISTORY_MAX_CONSECUTIVE_ERRORS)
    ]
