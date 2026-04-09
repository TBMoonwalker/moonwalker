"""Tests for bounded historical OHLCV fetches."""

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
    ) -> list[list[float]]:
        self.fetch_calls.append((symbol, timeframe, since, limit))
        return [
            [0, 1.0, 2.0, 0.5, 1.5, 10.0],
            [60_000, 1.5, 2.5, 1.0, 2.0, 10.0],
            [120_000, 2.0, 3.0, 1.5, 2.5, 10.0],
            [180_000, 2.5, 3.5, 2.0, 3.0, 10.0],
        ]


@pytest.mark.asyncio
async def test_get_history_for_symbol_respects_until_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = Exchange()
    exchange.exchange = _DummyHistoryExchange()

    async def fake_ensure_exchange(_config: dict[str, object]) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    monkeypatch.setattr(exchange, "_Exchange__ensure_exchange", fake_ensure_exchange)
    monkeypatch.setattr(
        exchange, "_Exchange__ensure_markets_loaded", fake_ensure_markets_loaded
    )
    monkeypatch.setattr(exchange, "_Exchange__resolve_symbol", lambda symbol: symbol)

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
