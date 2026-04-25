import os
from typing import Any

import model
import pytest
import service.orders as orders_module
from service.capital_budget_logic import evaluate_capital_budget
from service.orders import Orders
from tortoise import Tortoise


def test_capital_budget_uses_legacy_autopilot_max_fund_as_alias() -> None:
    check = evaluate_capital_budget(
        {
            "autopilot_max_fund": 100,
            "capital_reserve_safety_orders": False,
        },
        {"symbol": "BTC/USDT", "ordersize": 25.0},
        funds_locked=80.0,
        open_trade_reserve=0.0,
        pending_quote=0.0,
        closed_profit=0.0,
    )

    assert check.ok is False
    assert check.reason == "capital_budget_exceeded"
    assert check.principal_limit == 100.0


def test_capital_budget_stretches_only_realized_positive_profit() -> None:
    config = {
        "capital_max_fund": 100,
        "capital_reserve_safety_orders": False,
        "autopilot": True,
        "autopilot_profit_stretch_enabled": True,
        "autopilot_profit_stretch_ratio": 0.5,
        "autopilot_profit_stretch_max": 20,
    }

    stretched = evaluate_capital_budget(
        config,
        {"symbol": "BTC/USDT", "ordersize": 15.0},
        funds_locked=100.0,
        open_trade_reserve=0.0,
        pending_quote=0.0,
        closed_profit=50.0,
    )
    loss_case = evaluate_capital_budget(
        config,
        {"symbol": "BTC/USDT", "ordersize": 1.0},
        funds_locked=100.0,
        open_trade_reserve=0.0,
        pending_quote=0.0,
        closed_profit=-50.0,
    )

    assert stretched.ok is True
    assert stretched.effective_limit == 120.0
    assert stretched.stretch_quote == 20.0
    assert loss_case.ok is False
    assert loss_case.effective_limit == 100.0


@pytest.mark.asyncio
async def test_receive_buy_order_blocks_live_buy_over_global_cap(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    try:
        await model.OpenTrades.create(symbol="ETH/USDT", cost=90.0, so_count=0)
        orders = Orders()
        exchange_calls = {"count": 0}

        async def fake_create_spot_market_buy(_order, _config) -> None:
            exchange_calls["count"] += 1
            return None

        async def fake_close() -> None:
            return None

        monkeypatch.setattr(
            orders.exchange,
            "create_spot_market_buy",
            fake_create_spot_market_buy,
        )
        monkeypatch.setattr(orders.exchange, "close", fake_close)

        result = await orders.receive_buy_order(
            {
                "ordersize": 20.0,
                "symbol": "BTC/USDT",
                "direction": "long",
                "botname": "asap_BTC/USDT",
                "baseorder": True,
                "safetyorder": False,
                "order_count": 0,
                "ordertype": "market",
                "so_percentage": None,
                "side": "buy",
            },
            {
                "capital_max_fund": 100.0,
                "capital_reserve_safety_orders": False,
            },
        )

        assert result is False
        assert exchange_calls["count"] == 0
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_manual_ledger_buy_add_warns_but_persists_when_over_budget(
    monkeypatch,
) -> None:
    orders = Orders()
    persisted: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def fake_get_open_trades_by_symbol(_symbol: str) -> list[dict[str, Any]]:
        return [
            {
                "symbol": "BTC/USDC",
                "so_count": 1,
                "amount": 1.0,
                "cost": 100.0,
            }
        ]

    async def fake_get_trades_by_symbol(_symbol: str) -> list[dict[str, Any]]:
        return [
            {"timestamp": "1000", "price": 100.0, "baseorder": True},
            {"timestamp": "2000", "price": 90.0, "safetyorder": True},
        ]

    async def fake_get_trades_for_orders(_symbol: str) -> dict[str, Any]:
        return {
            "safetyorders_count": 1,
            "bot": "asap_BTC/USDC",
            "ordertype": "market",
            "direction": "long",
        }

    async def fake_persist_manual_buy_add(
        symbol: str,
        trade_payload: dict[str, Any],
        open_trade_payload: dict[str, Any],
    ) -> None:
        persisted.append((symbol, trade_payload, open_trade_payload))

    monkeypatch.setattr(
        orders.trades,
        "get_open_trades_by_symbol",
        fake_get_open_trades_by_symbol,
    )
    monkeypatch.setattr(
        orders.trades,
        "get_trades_by_symbol",
        fake_get_trades_by_symbol,
    )
    monkeypatch.setattr(
        orders.trades,
        "get_trades_for_orders",
        fake_get_trades_for_orders,
    )
    monkeypatch.setattr(
        orders_module,
        "persist_manual_buy_add",
        fake_persist_manual_buy_add,
    )

    async def fake_budget_warning(*_args, **_kwargs) -> dict[str, Any]:
        return {"reason": "capital_budget_exceeded"}

    monkeypatch.setattr(
        orders,
        "_build_manual_buy_budget_warning",
        fake_budget_warning,
    )

    result = await orders.receive_manual_buy_add(
        symbol="BTC/USDC",
        date_input="3000",
        price_raw=80.0,
        amount_raw=0.5,
        config={"capital_max_fund": 100.0},
    )

    assert result["capital_budget_warning"]["reason"] == "capital_budget_exceeded"
    assert persisted
