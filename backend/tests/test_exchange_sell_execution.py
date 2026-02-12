import pytest

from service.exchange import Exchange


@pytest.mark.asyncio
async def test_create_spot_sell_uses_limit_when_enabled(monkeypatch):
    exchange = Exchange()
    calls = {"limit": 0, "market": 0}

    async def fake_limit_sell(_order, _config):
        calls["limit"] += 1
        return {"path": "limit"}

    async def fake_market_sell(_order, _config):
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
async def test_create_spot_sell_falls_back_to_market(monkeypatch):
    exchange = Exchange()
    calls = {"limit": 0, "market": 0}

    async def fake_limit_sell(_order, _config):
        calls["limit"] += 1
        return None

    async def fake_market_sell(_order, _config):
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
async def test_create_spot_sell_skips_fallback_when_disabled(monkeypatch):
    exchange = Exchange()
    calls = {"limit": 0, "market": 0}

    async def fake_limit_sell(_order, _config):
        calls["limit"] += 1
        return None

    async def fake_market_sell(_order, _config):
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
async def test_create_spot_sell_defaults_to_market(monkeypatch):
    exchange = Exchange()
    calls = {"market": 0}

    async def fake_market_sell(_order, _config):
        calls["market"] += 1
        return {"path": "market"}

    monkeypatch.setattr(exchange, "create_spot_market_sell", fake_market_sell)

    result = await exchange.create_spot_sell({"symbol": "BTC/USDT"}, {})

    assert result == {"path": "market"}
    assert calls["market"] == 1
