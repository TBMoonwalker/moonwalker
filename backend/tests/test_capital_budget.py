import os
from typing import Any

import model
import pytest
import service.capital_budget_logic as capital_budget_logic
import service.orders as orders_module
from service.capital_budget import CapitalBudgetService
from service.orders import Orders
from tortoise import Tortoise


def test_capital_budget_uses_legacy_autopilot_max_fund_as_alias() -> None:
    check = capital_budget_logic.evaluate_capital_budget(
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

    stretched = capital_budget_logic.evaluate_capital_budget(
        config,
        {"symbol": "BTC/USDT", "ordersize": 15.0},
        funds_locked=100.0,
        open_trade_reserve=0.0,
        pending_quote=0.0,
        closed_profit=50.0,
    )
    loss_case = capital_budget_logic.evaluate_capital_budget(
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


def test_base_order_reserves_baseline_ladder() -> None:
    config = {
        "capital_max_fund": 10_000,
        "capital_reserve_safety_orders": True,
        "dynamic_dca": True,
        "mstc": 5,
        "autopilot": True,
        "autopilot_profit_stretch_enabled": True,
        "autopilot_profit_stretch_ratio": 1.0,
        "autopilot_profit_stretch_max": 1_000,
    }

    check = capital_budget_logic.evaluate_capital_budget(
        config,
        {
            "symbol": "NIL/USDC",
            "ordersize": 12.0,
            "baseorder": True,
        },
        funds_locked=0.0,
        open_trade_reserve=0.0,
        pending_quote=0.0,
        closed_profit=1_000.0,
    )

    assert check.ok is True
    assert check.required_quote == 72.0


def test_missing_safety_reserve_config_defaults_to_order_only_requirement() -> None:
    check = capital_budget_logic.evaluate_capital_budget(
        {
            "capital_max_fund": 100.0,
            "dynamic_dca": True,
            "mstc": 5,
        },
        {
            "symbol": "PARTI/USDC",
            "ordersize": 12.0,
            "baseorder": True,
        },
        funds_locked=0.0,
        open_trade_reserve=0.0,
        pending_quote=0.0,
        closed_profit=0.0,
    )

    assert check.ok is True
    assert check.reserve_safety_orders is False
    assert check.required_quote == 12.0


def test_stretched_safety_order_consumes_only_extra_budget_above_reserve() -> None:
    config = {
        "capital_reserve_safety_orders": True,
        "dynamic_dca": True,
        "bo": 12.0,
        "mstc": 5,
        "autopilot": True,
        "autopilot_profit_stretch_enabled": True,
    }

    order_quote, required_quote = (
        capital_budget_logic.calculate_order_budget_requirement(
            config,
            {
                "symbol": "NIL/USDC",
                "ordersize": 30.0,
                "baseorder": False,
                "safetyorder": True,
                "order_count": 1,
            },
        )
    )

    assert order_quote == 30.0
    assert required_quote == 18.0


def test_capital_budget_buffer_accepts_ui_percent_and_api_ratio() -> None:
    assert capital_budget_logic.normalize_buffer_pct(50) == 0.5
    assert capital_budget_logic.normalize_buffer_pct("0.5") == 0.5
    assert capital_budget_logic.normalize_buffer_pct("2") == 0.02

    percent_input = capital_budget_logic.evaluate_capital_budget(
        {
            "capital_max_fund": 10_000,
            "capital_reserve_safety_orders": True,
            "capital_budget_buffer_pct": 50,
            "dynamic_dca": True,
            "mstc": 5,
        },
        {
            "symbol": "CGPT/USDC",
            "ordersize": 12.0,
            "baseorder": True,
        },
        funds_locked=0.0,
        open_trade_reserve=0.0,
        pending_quote=0.0,
        closed_profit=0.0,
    )

    ratio_input = capital_budget_logic.evaluate_capital_budget(
        {
            "capital_max_fund": 10_000,
            "capital_reserve_safety_orders": True,
            "capital_budget_buffer_pct": 0.5,
            "dynamic_dca": True,
            "mstc": 5,
        },
        {
            "symbol": "CGPT/USDC",
            "ordersize": 12.0,
            "baseorder": True,
        },
        funds_locked=0.0,
        open_trade_reserve=0.0,
        pending_quote=0.0,
        closed_profit=0.0,
    )

    assert percent_input.required_quote == 108.0
    assert ratio_input.required_quote == 108.0


def test_capital_budget_buffer_is_ignored_for_static_dca() -> None:
    result = capital_budget_logic.evaluate_capital_budget(
        {
            "capital_max_fund": 10_000,
            "capital_reserve_safety_orders": True,
            "capital_budget_buffer_pct": 50,
            "dynamic_dca": False,
            "so": 10,
            "mstc": 2,
            "os": 2,
        },
        {
            "symbol": "CGPT/USDC",
            "ordersize": 12.0,
            "baseorder": True,
        },
        funds_locked=0.0,
        open_trade_reserve=0.0,
        pending_quote=0.0,
        closed_profit=0.0,
    )

    assert result.required_quote == 42.0
    assert result.buffer_pct == 0.0


def test_open_trade_reserve_is_zero_when_safety_reserve_is_disabled() -> None:
    reserve = capital_budget_logic.estimate_open_trade_reserve(
        {
            "capital_reserve_safety_orders": False,
            "dynamic_dca": False,
            "so": 1200.0,
            "mstc": 5,
            "os": 2.0,
        },
        [
            {
                "symbol": "PARTI/USDC",
                "so_count": 0,
                "cost": 12.0,
            }
        ],
    )

    assert reserve == 0.0


@pytest.mark.asyncio
async def test_runtime_state_does_not_subtract_reserve_when_disabled(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    try:
        await model.OpenTrades.create(symbol="PARTI/USDC", cost=12.0, so_count=0)
        service = CapitalBudgetService()

        state = await service.get_runtime_state(
            {
                "capital_max_fund": 2000.0,
                "capital_reserve_safety_orders": False,
                "dynamic_dca": False,
                "so": 1200.0,
                "mstc": 5,
                "os": 2.0,
            }
        )

        assert state["capital_budget_available"] is True
        assert state["capital_funds_locked"] == 12.0
        assert state["capital_open_trade_reserve"] == 0.0
        assert state["capital_available_quote"] == 1988.0
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_runtime_state_reserves_baseline_dca_ladder_when_enabled(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    try:
        await model.OpenTrades.create(symbol="PARTI/USDC", cost=12.0, so_count=0)
        service = CapitalBudgetService()

        state = await service.get_runtime_state(
            {
                "capital_max_fund": 2000.0,
                "capital_reserve_safety_orders": True,
                "dynamic_dca": True,
                "bo": 12.0,
                "mstc": 5,
            }
        )

        assert state["capital_budget_available"] is True
        assert state["capital_funds_locked"] == 12.0
        assert state["capital_open_trade_reserve"] == 60.0
        assert state["capital_available_quote"] == 1928.0
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_capital_budget_lease_blocks_overlapping_buy_admission(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    service = CapitalBudgetService()
    CapitalBudgetService._leases.clear()

    try:
        first_lease, first_check = await service.acquire_order_lease(
            {"symbol": "BTC/USDT", "ordersize": 60.0},
            {
                "capital_max_fund": 100.0,
                "capital_reserve_safety_orders": False,
            },
        )
        second_lease, second_check = await service.acquire_order_lease(
            {"symbol": "ETH/USDT", "ordersize": 50.0},
            {
                "capital_max_fund": 100.0,
                "capital_reserve_safety_orders": False,
            },
        )
        await second_lease.release()

        assert first_check.ok is True
        assert second_check.ok is False
        assert second_check.reason == "capital_budget_exceeded"
        assert second_check.pending_quote == 60.0

        await first_lease.release()
        third_lease, third_check = await service.acquire_order_lease(
            {"symbol": "SOL/USDT", "ordersize": 50.0},
            {
                "capital_max_fund": 100.0,
                "capital_reserve_safety_orders": False,
            },
        )
        await third_lease.release()

        assert third_check.ok is True
        assert CapitalBudgetService._pending_reserved_quote() == 0.0
    finally:
        CapitalBudgetService._leases.clear()
        await Tortoise.close_connections()


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
