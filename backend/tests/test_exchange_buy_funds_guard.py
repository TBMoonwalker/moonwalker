import pytest
from service.exchange import Exchange


@pytest.mark.asyncio
async def test_create_spot_market_buy_skips_when_quote_balance_is_zero(
    monkeypatch,
) -> None:
    exchange = Exchange()
    execute_calls = {"count": 0}

    async def fake_ensure_exchange(_config) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_get_amount(_ordersize, _symbol) -> str:
        return "0.001"

    async def fake_get_price(_symbol) -> str:
        return "100000.0"

    async def fake_get_free_quote_balance(
        config=None, symbol=None, force_refresh=False
    ) -> float:
        assert config is not None
        assert symbol == "BTC/USDT"
        assert force_refresh is True
        return 0.0

    async def fake_execute(_order) -> None:
        execute_calls["count"] += 1
        return None

    monkeypatch.setattr(exchange, "_Exchange__ensure_exchange", fake_ensure_exchange)
    monkeypatch.setattr(
        exchange, "_Exchange__ensure_markets_loaded", fake_ensure_markets_loaded
    )
    monkeypatch.setattr(exchange, "_Exchange__resolve_symbol", lambda symbol: symbol)
    monkeypatch.setattr(exchange, "_Exchange__get_amount_from_symbol", fake_get_amount)
    monkeypatch.setattr(exchange, "_Exchange__get_price_for_symbol", fake_get_price)
    monkeypatch.setattr(exchange, "get_free_quote_balance", fake_get_free_quote_balance)
    monkeypatch.setattr(exchange, "_Exchange__execute_market_buy", fake_execute)

    result = await exchange.create_spot_market_buy(
        {"ordersize": 100.0, "symbol": "BTC/USDT"},
        {},
    )

    assert result is None
    assert execute_calls["count"] == 0
    precheck = exchange.get_last_buy_precheck_result()
    assert precheck is not None
    assert precheck["ok"] is False
    assert precheck["reason"] == "insufficient_quote_balance"


@pytest.mark.asyncio
async def test_create_spot_market_buy_skips_when_balance_check_unavailable(
    monkeypatch,
) -> None:
    exchange = Exchange()
    execute_calls = {"count": 0}

    async def fake_ensure_exchange(_config) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_get_amount(_ordersize, _symbol) -> str:
        return "0.001"

    async def fake_get_price(_symbol) -> str:
        return "100000.0"

    async def fake_get_free_quote_balance(
        config=None, symbol=None, force_refresh=False
    ) -> None:
        assert config is not None
        assert symbol == "BTC/USDT"
        assert force_refresh is True
        return None

    async def fake_execute(_order) -> None:
        execute_calls["count"] += 1
        return None

    monkeypatch.setattr(exchange, "_Exchange__ensure_exchange", fake_ensure_exchange)
    monkeypatch.setattr(
        exchange, "_Exchange__ensure_markets_loaded", fake_ensure_markets_loaded
    )
    monkeypatch.setattr(exchange, "_Exchange__resolve_symbol", lambda symbol: symbol)
    monkeypatch.setattr(exchange, "_Exchange__get_amount_from_symbol", fake_get_amount)
    monkeypatch.setattr(exchange, "_Exchange__get_price_for_symbol", fake_get_price)
    monkeypatch.setattr(exchange, "get_free_quote_balance", fake_get_free_quote_balance)
    monkeypatch.setattr(exchange, "_Exchange__execute_market_buy", fake_execute)

    result = await exchange.create_spot_market_buy(
        {"ordersize": 100.0, "symbol": "BTC/USDT"},
        {},
    )

    assert result is None
    assert execute_calls["count"] == 0
    precheck = exchange.get_last_buy_precheck_result()
    assert precheck is not None
    assert precheck["ok"] is False
    assert precheck["reason"] == "balance_unavailable"


@pytest.mark.asyncio
async def test_create_spot_market_buy_runs_when_quote_balance_is_sufficient(
    monkeypatch,
) -> None:
    exchange = Exchange()
    execute_calls = {"count": 0}

    async def fake_ensure_exchange(_config) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_get_amount(_ordersize, _symbol) -> str:
        return "0.001"

    async def fake_get_price(_symbol) -> str:
        return "100000.0"

    async def fake_get_free_quote_balance(
        config=None, symbol=None, force_refresh=False
    ) -> float:
        assert config is not None
        assert symbol == "BTC/USDT"
        assert force_refresh is True
        return 100.0

    async def fake_execute(_order) -> None:
        execute_calls["count"] += 1
        return None

    monkeypatch.setattr(exchange, "_Exchange__ensure_exchange", fake_ensure_exchange)
    monkeypatch.setattr(
        exchange, "_Exchange__ensure_markets_loaded", fake_ensure_markets_loaded
    )
    monkeypatch.setattr(exchange, "_Exchange__resolve_symbol", lambda symbol: symbol)
    monkeypatch.setattr(exchange, "_Exchange__get_amount_from_symbol", fake_get_amount)
    monkeypatch.setattr(exchange, "_Exchange__get_price_for_symbol", fake_get_price)
    monkeypatch.setattr(exchange, "get_free_quote_balance", fake_get_free_quote_balance)
    monkeypatch.setattr(exchange, "_Exchange__execute_market_buy", fake_execute)

    result = await exchange.create_spot_market_buy(
        {"ordersize": 100.0, "symbol": "BTC/USDT"},
        {},
    )

    assert result is None
    assert execute_calls["count"] == 1
    precheck = exchange.get_last_buy_precheck_result()
    assert precheck is not None
    assert precheck["ok"] is True


@pytest.mark.asyncio
async def test_create_spot_market_buy_records_invalid_price_or_amount_reason(
    monkeypatch,
) -> None:
    exchange = Exchange()

    async def fake_ensure_exchange(_config) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_get_amount(_ordersize, _symbol) -> str:
        return "0"

    async def fake_get_price(_symbol) -> str:
        return "100000.0"

    monkeypatch.setattr(exchange, "_Exchange__ensure_exchange", fake_ensure_exchange)
    monkeypatch.setattr(
        exchange, "_Exchange__ensure_markets_loaded", fake_ensure_markets_loaded
    )
    monkeypatch.setattr(exchange, "_Exchange__get_amount_from_symbol", fake_get_amount)
    monkeypatch.setattr(exchange, "_Exchange__get_price_for_symbol", fake_get_price)

    result = await exchange.create_spot_market_buy(
        {"ordersize": 5.0, "symbol": "BTC/USDT"},
        {},
    )

    assert result is None
    precheck = exchange.get_last_buy_precheck_result()
    assert precheck is not None
    assert precheck["ok"] is False
    assert precheck["reason"] == "invalid_price_or_amount"


class _RefreshingTickerExchange:
    def __init__(self) -> None:
        self.fetch_calls = 0

    async def fetch_ticker(self, _symbol: str) -> dict[str, float]:
        self.fetch_calls += 1
        return {"last": 42.5}

    def price_to_precision(self, _symbol: str, price: float) -> str:
        return f"{price:.1f}"


@pytest.mark.asyncio
async def test_price_lookup_refreshes_markets_when_symbol_is_missing(
    monkeypatch,
) -> None:
    exchange = Exchange()
    exchange.exchange = _RefreshingTickerExchange()
    state = {"resolved": False, "refresh_calls": 0}

    async def fake_ensure_markets_loaded(force_refresh: bool = False) -> None:
        if force_refresh:
            state["resolved"] = True
            state["refresh_calls"] += 1

    monkeypatch.setattr(
        exchange._client_manager,
        "ensure_markets_loaded",
        fake_ensure_markets_loaded,
    )
    monkeypatch.setattr(
        exchange,
        "_Exchange__resolve_symbol",
        lambda symbol: symbol if state["resolved"] else None,
    )

    price = await exchange._Exchange__get_price_for_symbol("SAHARA/USDC")

    assert price == "42.5"
    assert state["refresh_calls"] == 1
    assert exchange.exchange.fetch_calls == 1
