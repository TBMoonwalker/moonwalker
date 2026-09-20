import os

import pytest
from service.orders import Orders
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_receive_sell_order_archives_unsellable_remainder(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    await model.Trades.create(
        timestamp="1773580000000",
        ordersize=11.98,
        fee=0.001,
        precision=3,
        amount=5.13,
        amount_fee=0.0,
        price=2.335282651,
        symbol="LPT/USDC",
        orderid="oid1",
        bot="asap_LPT/USDC",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
    )
    await model.OpenTrades.create(
        symbol="LPT/USDC",
        so_count=0,
        amount=5.13,
        cost=11.98,
        current_price=2.274,
        avg_price=2.335282651,
        open_date="1773580000000",
    )

    orders = Orders()
    notified_events: list[tuple[str, dict]] = []

    async def fake_create_spot_sell(_order, _config):
        return {
            "type": "partial_sell",
            "symbol": "LPT/USDC",
            "partial_filled_amount": 5.12,
            "partial_proceeds": 11.64288,
            "remaining_amount": 0.01,
            "unsellable": True,
            "unsellable_reason": "minimum_notional",
            "unsellable_min_notional": 10.0,
            "unsellable_estimated_notional": 0.02274,
        }

    async def fake_close() -> None:
        return None

    async def fake_notify(event_type: str, payload: dict, _config: dict) -> None:
        notified_events.append((event_type, payload))

    monkeypatch.setattr(orders.exchange, "create_spot_sell", fake_create_spot_sell)
    monkeypatch.setattr(orders.exchange, "close", fake_close)
    monkeypatch.setattr(orders.monitoring, "notify_trade", fake_notify)

    await orders.receive_sell_order(
        {
            "symbol": "LPT/USDC",
            "direction": "long",
            "side": "sell",
            "type_sell": "order_sell",
            "actual_pnl": -2.84,
            "total_cost": 11.98,
            "current_price": 2.274,
        },
        {"tp": 1.0, "monitoring_enabled": True},
    )

    assert await model.OpenTrades.all().count() == 0
    assert await model.Trades.all().count() == 0

    closed_trade = await model.ClosedTrades.all().first()
    assert closed_trade is not None
    assert closed_trade.symbol == "LPT/USDC"
    assert closed_trade.amount == pytest.approx(5.12)
    assert closed_trade.cost == pytest.approx(11.95664717)

    unsellable_trade = await model.UnsellableTrades.all().first()
    assert unsellable_trade is not None
    assert unsellable_trade.symbol == "LPT/USDC"
    assert unsellable_trade.amount == pytest.approx(0.01)
    assert unsellable_trade.cost == pytest.approx(0.02335283)
    assert unsellable_trade.current_price == pytest.approx(2.274)
    assert unsellable_trade.unsellable_reason == "minimum_notional"
    assert unsellable_trade.unsellable_min_notional == pytest.approx(10.0)
    assert unsellable_trade.unsellable_estimated_notional == pytest.approx(0.02274)

    assert len(notified_events) == 1
    assert notified_events[0][0] == "trade.unsellable_notional"

    await Tortoise.close_connections()
