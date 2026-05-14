import pytest
from service.orders import Orders


@pytest.mark.asyncio
async def test_receive_buy_order_rejects_global_pause(monkeypatch) -> None:
    orders = Orders()
    executed = 0

    async def fake_get_trades_for_orders(_symbol: str):
        return None

    async def fail_execute_budgeted_buy_order(*_args, **_kwargs):
        nonlocal executed
        executed += 1
        raise AssertionError("buy execution should be blocked before exchange work")

    monkeypatch.setattr(
        orders.trades,
        "get_trades_for_orders",
        fake_get_trades_for_orders,
    )
    monkeypatch.setattr(
        orders,
        "_execute_budgeted_buy_order",
        fail_execute_budgeted_buy_order,
    )

    accepted = await orders.receive_buy_order(
        {
            "symbol": "BTC/USDT",
            "ordersize": 100.0,
            "baseorder": True,
            "safetyorder": False,
        },
        {"trading_paused": True},
    )

    assert accepted is False
    assert executed == 0


@pytest.mark.asyncio
async def test_receive_buy_order_rejects_paused_mission(monkeypatch) -> None:
    orders = Orders()
    executed = 0

    async def fake_get_trades_for_orders(_symbol: str):
        return {
            "symbol": "BTC/USDT",
            "automation_paused": True,
        }

    async def fail_execute_budgeted_buy_order(*_args, **_kwargs):
        nonlocal executed
        executed += 1
        raise AssertionError("buy execution should be blocked before exchange work")

    monkeypatch.setattr(
        orders.trades,
        "get_trades_for_orders",
        fake_get_trades_for_orders,
    )
    monkeypatch.setattr(
        orders,
        "_execute_budgeted_buy_order",
        fail_execute_budgeted_buy_order,
    )

    accepted = await orders.receive_buy_order(
        {
            "symbol": "BTC/USDT",
            "ordersize": 100.0,
            "baseorder": False,
            "safetyorder": True,
        },
        {},
    )

    assert accepted is False
    assert executed == 0
