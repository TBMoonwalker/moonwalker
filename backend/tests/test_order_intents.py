from typing import Any

import pytest
from service.order_intents import (
    build_manual_buy_order_intent,
    build_manual_sell_order_intent,
)
from service.orders import Orders


def test_build_manual_sell_order_intent_returns_expected_payload() -> None:
    order = build_manual_sell_order_intent(
        {
            "symbol": "BTC/USDT",
            "direction": "long",
            "total_cost": 25000.0,
            "current_price": 26000.0,
        },
        actual_pnl=4.0,
    )

    assert order == {
        "symbol": "BTC/USDT",
        "direction": "long",
        "side": "sell",
        "type_sell": "order_sell",
        "actual_pnl": 4.0,
        "total_cost": 25000.0,
        "current_price": 26000.0,
    }


def test_build_manual_buy_order_intent_counts_existing_safety_orders() -> None:
    order = build_manual_buy_order_intent(
        "ETH/USDT",
        50.0,
        {
            "direction": "long",
            "bot": "asap_ETH/USDT",
            "safetyorders": [{}, {}],
        },
        actual_pnl=-7.25,
    )

    assert order == {
        "ordersize": 50.0,
        "symbol": "ETH/USDT",
        "direction": "long",
        "botname": "asap_ETH/USDT",
        "baseorder": False,
        "safetyorder": True,
        "order_count": 3,
        "ordertype": "market",
        "so_percentage": -7.25,
        "side": "buy",
    }


@pytest.mark.asyncio
async def test_receive_sell_signal_returns_false_when_trade_context_missing(
    monkeypatch,
) -> None:
    orders = Orders()
    deleted_symbols: list[str] = []

    async def fake_get_trades_for_orders(_symbol: str) -> None:
        return None

    async def fake_delete_open_trades(symbol: str) -> None:
        deleted_symbols.append(symbol)

    monkeypatch.setattr(
        orders.trades,
        "get_trades_for_orders",
        fake_get_trades_for_orders,
    )
    monkeypatch.setattr(
        orders.trades,
        "delete_open_trades",
        fake_delete_open_trades,
    )

    result = await orders.receive_sell_signal("btc-usdt", {})

    assert result is False
    assert deleted_symbols == ["BTC/USDT"]


@pytest.mark.asyncio
async def test_receive_buy_signal_builds_and_dispatches_manual_buy_order(
    monkeypatch,
) -> None:
    orders = Orders()
    dispatched: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def fake_get_trades_for_orders(_symbol: str) -> dict[str, Any]:
        return {
            "symbol": "ETH/USDT",
            "direction": "long",
            "bot": "asap_ETH/USDT",
            "current_price": 900.0,
            "total_cost": 1000.0,
            "fee": 0.0,
            "total_amount": 1.0,
            "safetyorders": [{"price": 950.0}],
        }

    async def fake_receive_buy_order(
        order: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        dispatched.append((order, config))
        return True

    monkeypatch.setattr(
        orders.trades,
        "get_trades_for_orders",
        fake_get_trades_for_orders,
    )
    monkeypatch.setattr(orders, "receive_buy_order", fake_receive_buy_order)

    result = await orders.receive_buy_signal("eth-usdt", 25.0, {"dry_run": True})

    assert result is True
    assert dispatched == [
        (
            {
                "ordersize": 25.0,
                "symbol": "ETH/USDT",
                "direction": "long",
                "botname": "asap_ETH/USDT",
                "baseorder": False,
                "safetyorder": True,
                "order_count": 2,
                "ordertype": "market",
                "so_percentage": -10.0,
                "side": "buy",
            },
            {"dry_run": True},
        )
    ]
