"""Price selection for ticker fetches used by exit price guards."""

import pytest
from service.exchange import Exchange
from tenacity import RetryError, stop_after_attempt, wait_none


class _TickerExchange:
    def __init__(self, ticker: dict[str, float | None]) -> None:
        self.ticker = ticker
        self.fetched_symbols: list[str] = []

    def market(self, _symbol: str) -> dict[str, object]:
        return {"symbol": "BTC/USDC"}

    def price_to_precision(self, _symbol: str, price: float) -> str:
        return f"{price:.8f}"

    async def fetch_ticker(self, symbol: str) -> dict[str, float | None]:
        self.fetched_symbols.append(symbol)
        return self.ticker


def _make_exchange(ticker: dict[str, float | None]) -> tuple[Exchange, _TickerExchange]:
    exchange = Exchange()
    client = _TickerExchange(ticker)
    exchange.exchange = client
    return exchange, client


async def _resolve(_symbol: str) -> str:
    return "BTC/USDC"


@pytest.mark.asyncio
async def test_bid_fetch_initializes_client_and_markets(monkeypatch) -> None:
    exchange = Exchange()
    client = _TickerExchange({"bid": 100.0})
    events = []

    async def ensure_client(config):
        events.append(("client", config))
        exchange.exchange = client

    async def ensure_markets():
        assert exchange.exchange is client
        events.append(("markets",))

    monkeypatch.setattr(exchange, "_ensure_exchange", ensure_client)
    monkeypatch.setattr(exchange, "_ensure_markets_loaded", ensure_markets)
    monkeypatch.setattr(exchange, "_resolve_symbol_with_refresh", _resolve)
    config = {"exchange": "binance"}

    assert await exchange.get_bid_price_for_symbol("BTC/USDC", config) == "100.00000000"
    assert events == [("client", config), ("markets",)]
    assert client.fetched_symbols == ["BTC/USDC"]


def _neutralize_retry(exchange: Exchange, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail a missing price immediately instead of waiting through retries.

    The decorated fetcher shares one Tenacity instance across calls, so
    monkeypatch restores the production stop/wait after the test.
    """
    retry = exchange._get_price_for_symbol.retry
    monkeypatch.setattr(retry, "wait", wait_none())
    monkeypatch.setattr(retry, "stop", stop_after_attempt(1))


@pytest.mark.asyncio
async def test_get_price_for_symbol_prefers_bid_when_present(monkeypatch) -> None:
    exchange, client = _make_exchange({"bid": 100.0, "ask": 101.0, "last": 100.5})
    monkeypatch.setattr(exchange, "_resolve_symbol_with_refresh", _resolve)

    price = await exchange._get_price_for_symbol("BTC/USDC", prefer_bid=True)

    assert price == "100.00000000"
    assert client.fetched_symbols == ["BTC/USDC"]


@pytest.mark.asyncio
async def test_get_price_for_symbol_missing_bid_retries_instead_of_last(
    monkeypatch,
) -> None:
    exchange, _client = _make_exchange({"bid": None, "ask": 101.0, "last": 100.5})
    monkeypatch.setattr(exchange, "_resolve_symbol_with_refresh", _resolve)
    _neutralize_retry(exchange, monkeypatch)

    # A missing executable side must not be papered over with the last
    # trade; the fetcher retries like a missing price.
    with pytest.raises(RetryError):
        await exchange._get_price_for_symbol("BTC/USDC", prefer_bid=True)


@pytest.mark.asyncio
async def test_get_price_for_symbol_missing_ask_retries_instead_of_last(
    monkeypatch,
) -> None:
    exchange, _client = _make_exchange({"bid": 100.0, "ask": None, "last": 100.5})
    monkeypatch.setattr(exchange, "_resolve_symbol_with_refresh", _resolve)
    _neutralize_retry(exchange, monkeypatch)

    with pytest.raises(RetryError):
        await exchange._get_price_for_symbol("BTC/USDC", prefer_ask=True)


@pytest.mark.asyncio
async def test_get_price_for_symbol_uses_ask_when_requested(monkeypatch) -> None:
    exchange, _client = _make_exchange({"bid": 100.0, "ask": 101.0, "last": 100.5})
    monkeypatch.setattr(exchange, "_resolve_symbol_with_refresh", _resolve)

    price = await exchange._get_price_for_symbol("BTC/USDC", prefer_ask=True)

    assert price == "101.00000000"


@pytest.mark.asyncio
async def test_get_price_for_symbol_uses_last_by_default(monkeypatch) -> None:
    exchange, _client = _make_exchange({"bid": 100.0, "ask": 101.0, "last": 100.5})
    monkeypatch.setattr(exchange, "_resolve_symbol_with_refresh", _resolve)

    price = await exchange._get_price_for_symbol("BTC/USDC")

    assert price == "100.50000000"
