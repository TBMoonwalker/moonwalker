import os

import pytest
from service.trades import Trades
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_get_token_amount_from_trades_uses_net_amount(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    await model.Trades.create(
        timestamp="1",
        ordersize=10.0,
        fee=0.001,
        precision=3,
        amount=99.0,
        amount_fee=1.0,
        price=0.1,
        symbol="ABC/USDT",
        orderid="oid1",
        bot="bot",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
    )

    trades = Trades()
    total_amount = await trades.get_token_amount_from_trades("ABC/USDT")

    assert total_amount == 99.0
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_trades_for_orders_uses_net_amount(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    await model.Trades.create(
        timestamp="1",
        ordersize=10.0,
        fee=0.001,
        precision=3,
        amount=99.0,
        amount_fee=1.0,
        price=0.1,
        symbol="ABC/USDT",
        orderid="oid1",
        bot="bot",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
    )

    trades = Trades()
    aggregated = await trades.get_trades_for_orders("ABC/USDT")

    assert aggregated is not None
    assert aggregated["total_amount"] == 99.0
    await Tortoise.close_connections()
