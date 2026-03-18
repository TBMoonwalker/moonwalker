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


@pytest.mark.asyncio
async def test_get_partial_sell_execution_reads_open_trade_totals(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    await model.OpenTrades.create(
        symbol="ABC/USDT",
        sold_amount=1.25,
        sold_proceeds=126.5,
    )

    trades = Trades()
    sold_amount, sold_proceeds = await trades.get_partial_sell_execution("ABC/USDT")

    assert sold_amount == 1.25
    assert sold_proceeds == 126.5
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_trades_for_orders_uses_unsellable_open_trade_amounts(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    await model.Trades.create(
        timestamp="1",
        ordersize=100.0,
        fee=0.001,
        precision=3,
        amount=1.0,
        amount_fee=0.0,
        price=100.0,
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
    await model.OpenTrades.create(
        symbol="ABC/USDT",
        amount=0.4,
        cost=42.0,
        current_price=120.0,
        unsellable_amount=0.4,
        unsellable_reason="minimum_notional",
        unsellable_min_notional=5.0,
        unsellable_estimated_notional=4.8,
    )

    trades = Trades()
    aggregated = await trades.get_trades_for_orders("ABC/USDT")

    assert aggregated is not None
    assert aggregated["is_unsellable"] is True
    assert aggregated["total_amount"] == 0.4
    assert aggregated["total_cost"] == 42.0
    assert aggregated["unsellable_reason"] == "minimum_notional"
    assert aggregated["unsellable_min_notional"] == 5.0
    assert aggregated["unsellable_estimated_notional"] == 4.8
    await Tortoise.close_connections()
