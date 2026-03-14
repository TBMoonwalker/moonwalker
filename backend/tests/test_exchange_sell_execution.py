import pytest
from service.exchange import Exchange


class _FakeMarketExchange:
    def __init__(self) -> None:
        self.market_sell_calls = 0

    def amount_to_precision(self, _symbol: str, amount: float) -> str:
        return f"{float(amount):.3f}"

    def market(self, _symbol: str) -> dict:
        return {
            "limits": {"cost": {"min": 5.0}},
            "info": {
                "filters": [
                    {
                        "filterType": "MIN_NOTIONAL",
                        "minNotional": "5",
                        "applyToMarket": True,
                    }
                ]
            },
        }

    async def create_market_sell_order(self, _symbol: str, _amount: float) -> dict:
        self.market_sell_calls += 1
        return {}


@pytest.mark.asyncio
async def test_create_spot_sell_uses_limit_when_enabled(monkeypatch) -> None:
    exchange = Exchange()
    calls = {"limit": 0, "market": 0}

    async def fake_limit_sell(_order, _config) -> None:
        calls["limit"] += 1
        return {"path": "limit"}

    async def fake_market_sell(_order, _config) -> None:
        calls["market"] += 1
        return {"path": "market"}

    monkeypatch.setattr(exchange, "create_spot_limit_sell", fake_limit_sell)
    monkeypatch.setattr(exchange, "create_spot_market_sell", fake_market_sell)

    result = await exchange.create_spot_sell(
        {"symbol": "BTC/USDT"},
        {"sell_order_type": "limit", "limit_sell_fallback_to_market": True},
    )

    assert result == {"path": "limit"}
    assert calls["limit"] == 1
    assert calls["market"] == 0


@pytest.mark.asyncio
async def test_create_spot_sell_falls_back_to_market(monkeypatch) -> None:
    exchange = Exchange()
    calls = {"limit": 0, "market": 0}

    async def fake_limit_sell(_order, _config) -> None:
        calls["limit"] += 1
        return {
            "requires_market_fallback": True,
            "limit_cancel_confirmed": True,
            "fallback_reason": "limit_order_timeout",
            "symbol": "BTC/USDT",
            "remaining_amount": 1.0,
            "partial_filled_amount": 0.0,
            "partial_avg_price": 0.0,
        }

    async def fake_market_sell(_order, _config) -> None:
        calls["market"] += 1
        return {"path": "market"}

    monkeypatch.setattr(exchange, "create_spot_limit_sell", fake_limit_sell)
    monkeypatch.setattr(exchange, "create_spot_market_sell", fake_market_sell)

    result = await exchange.create_spot_sell(
        {"symbol": "BTC/USDT"},
        {"sell_order_type": "limit", "limit_sell_fallback_to_market": True},
    )

    assert result == {"path": "market"}
    assert calls["limit"] == 1
    assert calls["market"] == 1


@pytest.mark.asyncio
async def test_create_spot_sell_skips_fallback_when_disabled(monkeypatch) -> None:
    exchange = Exchange()
    calls = {"limit": 0, "market": 0}

    async def fake_limit_sell(_order, _config) -> None:
        calls["limit"] += 1
        return None

    async def fake_market_sell(_order, _config) -> None:
        calls["market"] += 1
        return {"path": "market"}

    monkeypatch.setattr(exchange, "create_spot_limit_sell", fake_limit_sell)
    monkeypatch.setattr(exchange, "create_spot_market_sell", fake_market_sell)

    result = await exchange.create_spot_sell(
        {"symbol": "BTC/USDT"},
        {"sell_order_type": "limit", "limit_sell_fallback_to_market": False},
    )

    assert result is None
    assert calls["limit"] == 1
    assert calls["market"] == 0


@pytest.mark.asyncio
async def test_create_spot_sell_defaults_to_market(monkeypatch) -> None:
    exchange = Exchange()
    calls = {"market": 0}

    async def fake_market_sell(_order, _config) -> None:
        calls["market"] += 1
        return {"path": "market"}

    monkeypatch.setattr(exchange, "create_spot_market_sell", fake_market_sell)

    result = await exchange.create_spot_sell({"symbol": "BTC/USDT"}, {})

    assert result == {"path": "market"}
    assert calls["market"] == 1


@pytest.mark.asyncio
async def test_create_spot_sell_returns_partial_when_fallback_disabled(
    monkeypatch,
) -> None:
    exchange = Exchange()
    calls = {"limit": 0, "market": 0}

    async def fake_limit_sell(_order, _config) -> None:
        calls["limit"] += 1
        return {
            "requires_market_fallback": True,
            "limit_cancel_confirmed": True,
            "symbol": "ERA/USDC",
            "remaining_amount": 100.0,
            "partial_filled_amount": 40.0,
            "partial_avg_price": 0.1515,
        }

    async def fake_market_sell(_order, _config) -> None:
        calls["market"] += 1
        return {"path": "market"}

    monkeypatch.setattr(exchange, "create_spot_limit_sell", fake_limit_sell)
    monkeypatch.setattr(exchange, "create_spot_market_sell", fake_market_sell)

    result = await exchange.create_spot_sell(
        {"symbol": "ERA/USDC"},
        {"sell_order_type": "limit", "limit_sell_fallback_to_market": False},
    )

    assert result is not None
    assert result["type"] == "partial_sell"
    assert result["partial_filled_amount"] == 40.0
    assert result["partial_proceeds"] == pytest.approx(6.06)
    assert calls["limit"] == 1
    assert calls["market"] == 0


@pytest.mark.asyncio
async def test_create_spot_sell_returns_partial_when_tp_guard_blocks_fallback(
    monkeypatch,
) -> None:
    exchange = Exchange()
    calls = {"limit": 0, "market": 0, "guard": 0}

    async def fake_limit_sell(_order, _config) -> None:
        calls["limit"] += 1
        return {
            "requires_market_fallback": True,
            "limit_cancel_confirmed": True,
            "symbol": "ERA/USDC",
            "remaining_amount": 133.9,
            "partial_filled_amount": 69.5,
            "partial_avg_price": 0.1515,
        }

    async def fake_market_sell(_order, _config) -> None:
        calls["market"] += 1
        return {"path": "market"}

    async def fake_guard(_order, _config) -> None:
        calls["guard"] += 1
        return False

    monkeypatch.setattr(exchange, "create_spot_limit_sell", fake_limit_sell)
    monkeypatch.setattr(exchange, "create_spot_market_sell", fake_market_sell)
    monkeypatch.setattr(exchange, "_Exchange__can_fallback_to_market_sell", fake_guard)

    result = await exchange.create_spot_sell(
        {"symbol": "ERA/USDC"},
        {"sell_order_type": "limit", "limit_sell_fallback_to_market": True},
    )

    assert result is not None
    assert result["type"] == "partial_sell"
    assert result["partial_filled_amount"] == 69.5
    assert result["remaining_amount"] == 133.9
    assert calls["limit"] == 1
    assert calls["guard"] == 1
    assert calls["market"] == 0


@pytest.mark.asyncio
async def test_create_spot_sell_keeps_partial_fill_when_market_fallback_skips(
    monkeypatch,
) -> None:
    exchange = Exchange()
    calls = {"limit": 0, "market": 0}

    async def fake_limit_sell(_order, _config) -> None:
        calls["limit"] += 1
        return {
            "requires_market_fallback": True,
            "limit_cancel_confirmed": True,
            "symbol": "GMX/USDC",
            "remaining_amount": 0.679,
            "partial_filled_amount": 1.024,
            "partial_avg_price": 7.12,
        }

    async def fake_market_sell(_order, _config) -> None:
        calls["market"] += 1
        return {
            "type": "partial_sell",
            "symbol": "GMX/USDC",
            "partial_filled_amount": 0.0,
            "partial_avg_price": 0.0,
            "partial_proceeds": 0.0,
            "remaining_amount": 0.679,
        }

    monkeypatch.setattr(exchange, "create_spot_limit_sell", fake_limit_sell)
    monkeypatch.setattr(exchange, "create_spot_market_sell", fake_market_sell)

    result = await exchange.create_spot_sell(
        {
            "symbol": "GMX/USDC",
            "total_cost": 7.29,
            "total_amount": 1.70338025,
        },
        {"sell_order_type": "limit", "limit_sell_fallback_to_market": True},
    )

    assert result is not None
    assert result["type"] == "partial_sell"
    assert result["partial_filled_amount"] == pytest.approx(1.024)
    assert result["partial_avg_price"] == pytest.approx(7.12)
    assert result["remaining_amount"] == pytest.approx(0.679)
    assert result["partial_proceeds"] == pytest.approx(7.29088)
    assert calls["limit"] == 1
    assert calls["market"] == 1


@pytest.mark.asyncio
async def test_create_spot_market_sell_skips_below_notional(monkeypatch) -> None:
    exchange = Exchange()
    fake_exchange = _FakeMarketExchange()
    exchange.exchange = fake_exchange

    async def fake_ensure_exchange(_config) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_resolve_sell_amount(_symbol, _requested_amount) -> tuple[str, float]:
        return "GMX/USDC", 0.679

    async def fake_get_price_for_symbol(_symbol) -> str:
        return "7.13"

    monkeypatch.setattr(exchange, "_Exchange__ensure_exchange", fake_ensure_exchange)
    monkeypatch.setattr(
        exchange, "_Exchange__ensure_markets_loaded", fake_ensure_markets_loaded
    )
    monkeypatch.setattr(exchange, "_Exchange__resolve_symbol", lambda symbol: symbol)
    monkeypatch.setattr(
        exchange, "_Exchange__resolve_sell_amount", fake_resolve_sell_amount
    )
    monkeypatch.setattr(
        exchange, "_Exchange__get_price_for_symbol", fake_get_price_for_symbol
    )

    result = await exchange.create_spot_market_sell(
        {
            "symbol": "GMX/USDC",
            "total_amount": 1.70338025,
            "total_cost": 7.29,
            "actual_pnl": 0.0,
        },
        {},
    )

    assert result is not None
    assert result["type"] == "partial_sell"
    assert result["symbol"] == "GMX/USDC"
    assert result["partial_filled_amount"] == 0.0
    assert result["remaining_amount"] == pytest.approx(0.679)
    assert fake_exchange.market_sell_calls == 0


@pytest.mark.asyncio
async def test_market_fallback_guard_uses_order_current_price(monkeypatch) -> None:
    exchange = Exchange()

    async def fail_price_lookup(_symbol: str) -> str:
        raise AssertionError("ticker lookup should not run")

    monkeypatch.setattr(
        exchange,
        "_Exchange__get_price_for_symbol",
        fail_price_lookup,
    )

    allowed = await exchange._Exchange__can_fallback_to_market_sell(
        {
            "symbol": "SAHARA/USDC",
            "current_price": 0.02582,
            "fallback_min_price": 0.022749116460637608,
        },
        {"limit_sell_fallback_tp_guard": True},
    )

    assert allowed is True
