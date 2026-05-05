import os

import model
import pytest
from service.orders import Orders
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_receive_sell_order_uses_remaining_amount_after_partial_fill(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.Trades.create(
        timestamp="1777990000000",
        ordersize=12.1075,
        fee=0.001,
        precision=3,
        amount=725.0,
        amount_fee=0.0,
        price=0.0167,
        symbol="SENT/USDC",
        orderid="base-1",
        bot="asap_SENT/USDC",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
    )
    await model.OpenTrades.create(
        symbol="SENT/USDC",
        sold_amount=608.0,
        sold_proceeds=10.1536,
    )

    orders = Orders()
    submitted_orders: list[dict[str, float | str | bool]] = []

    async def fake_create_spot_sell(order, _config):
        submitted_orders.append(dict(order))
        return {
            "type": "partial_sell",
            "symbol": order["symbol"],
            "partial_filled_amount": 0.0,
            "partial_proceeds": 0.0,
            "remaining_amount": float(order["total_amount"]),
        }

    async def fake_close() -> None:
        return None

    monkeypatch.setattr(orders.exchange, "create_spot_sell", fake_create_spot_sell)
    monkeypatch.setattr(orders.exchange, "close", fake_close)

    await orders.receive_sell_order(
        {
            "symbol": "SENT/USDC",
            "direction": "long",
            "side": "sell",
            "type_sell": "order_sell",
            "actual_pnl": 0.0,
            "total_cost": 12.1075,
            "current_price": 0.0167,
            "skip_tp_limit_cancel": True,
        },
        {},
    )

    assert len(submitted_orders) == 1
    assert float(submitted_orders[0]["total_amount"]) == pytest.approx(117.0)

    await Tortoise.close_connections()
