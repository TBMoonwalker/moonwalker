import pytest
from service.exchange import Exchange


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
        return None

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
