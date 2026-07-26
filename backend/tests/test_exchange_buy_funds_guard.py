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

    async def fake_get_amount(_ordersize, _symbol, _price=None) -> str:
        return "0.001"

    async def fake_get_price(_symbol, **_kwargs) -> str:
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

    async def fake_get_amount(_ordersize, _symbol, _price=None) -> str:
        return "0.001"

    async def fake_get_price(_symbol, **_kwargs) -> str:
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

    async def fake_get_amount(_ordersize, _symbol, _price=None) -> str:
        return "0.001"

    async def fake_get_price(_symbol, **_kwargs) -> str:
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

    async def fake_get_amount(_ordersize, _symbol, _price=None) -> str:
        return "0"

    async def fake_get_price(_symbol, **_kwargs) -> str:
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


@pytest.mark.asyncio
async def test_recovery_buy_rejects_rebounded_executable_price(
    monkeypatch,
) -> None:
    exchange = Exchange()
    amount_calls = 0
    execute_calls = 0

    async def fake_ensure_exchange(_config) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_get_price(_symbol, **_kwargs) -> str:
        return "0.02016"

    async def fake_get_amount(_ordersize, _symbol, _price=None) -> str:
        nonlocal amount_calls
        amount_calls += 1
        return "286"

    async def fake_execute(_order) -> None:
        nonlocal execute_calls
        execute_calls += 1
        return None

    monkeypatch.setattr(exchange, "_Exchange__ensure_exchange", fake_ensure_exchange)
    monkeypatch.setattr(
        exchange, "_Exchange__ensure_markets_loaded", fake_ensure_markets_loaded
    )
    monkeypatch.setattr(exchange, "_Exchange__get_price_for_symbol", fake_get_price)
    monkeypatch.setattr(exchange, "_Exchange__get_amount_from_symbol", fake_get_amount)
    monkeypatch.setattr(exchange, "_Exchange__execute_market_buy", fake_execute)

    result = await exchange.create_spot_market_buy(
        {
            "ordersize": 5.766085,
            "symbol": "CVC/USDC",
            "maximum_buy_price": 0.019598,
        },
        {},
    )

    assert result is None
    assert amount_calls == 0
    assert execute_calls == 0
    precheck = exchange.get_last_buy_precheck_result()
    assert precheck is not None
    assert precheck["reason"] == "execution_price_above_maximum"
    assert precheck["executable_price"] == pytest.approx(0.02016)
    assert precheck["maximum_buy_price"] == pytest.approx(0.019598)


@pytest.mark.asyncio
async def test_unfilled_capped_buy_records_execution_guard_reason(
    monkeypatch,
) -> None:
    exchange = Exchange()

    async def fake_ensure_exchange(_config) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_get_price(_symbol, **_kwargs) -> str:
        return "0.01955"

    async def fake_get_amount(_ordersize, _symbol, price=None) -> str:
        assert float(price) == pytest.approx(0.019598)
        return "294"

    async def fake_get_free_quote_balance(
        config=None, symbol=None, force_refresh=False
    ) -> float:
        return 100.0

    async def fake_execute(_order) -> None:
        return None

    monkeypatch.setattr(exchange, "_Exchange__ensure_exchange", fake_ensure_exchange)
    monkeypatch.setattr(
        exchange, "_Exchange__ensure_markets_loaded", fake_ensure_markets_loaded
    )
    monkeypatch.setattr(exchange, "_Exchange__resolve_symbol", lambda symbol: symbol)
    monkeypatch.setattr(exchange, "_Exchange__get_price_for_symbol", fake_get_price)
    monkeypatch.setattr(exchange, "_Exchange__get_amount_from_symbol", fake_get_amount)
    monkeypatch.setattr(exchange, "get_free_quote_balance", fake_get_free_quote_balance)
    monkeypatch.setattr(exchange, "_Exchange__execute_market_buy", fake_execute)

    result = await exchange.create_spot_market_buy(
        {
            "ordersize": 5.766085,
            "symbol": "CVC/USDC",
            "maximum_buy_price": 0.019598,
        },
        {},
    )

    assert result is None
    precheck = exchange.get_last_buy_precheck_result()
    assert precheck is not None
    assert precheck["reason"] == "execution_ceiling_not_filled"


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


@pytest.mark.asyncio
async def test_buy_price_lookup_prefers_executable_ask(monkeypatch) -> None:
    exchange = Exchange()
    exchange.exchange = _RefreshingTickerExchange()

    async def fake_fetch_ticker(_symbol: str) -> dict[str, float]:
        return {"last": 42.5, "ask": 43.0}

    async def fake_resolve(symbol: str) -> str:
        return symbol

    exchange.exchange.fetch_ticker = fake_fetch_ticker
    monkeypatch.setattr(
        exchange,
        "_Exchange__resolve_symbol_with_refresh",
        fake_resolve,
    )

    price = await exchange._Exchange__get_price_for_symbol(
        "SAHARA/USDC",
        prefer_ask=True,
    )

    assert price == "43.0"
