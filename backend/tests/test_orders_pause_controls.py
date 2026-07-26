import pytest
import service.orders as orders_module
from service.ai_trust import AiTrustEntryGate
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
async def test_receive_buy_order_rejects_ai_warning_enforced_entry(
    monkeypatch,
) -> None:
    orders = Orders()
    executed = 0

    async def fake_get_trades_for_orders(_symbol: str):
        return None

    async def fake_ai_gate(_symbol, _order, _config):
        return AiTrustEntryGate(
            allowed=False,
            evaluated=True,
            provider_status="scored",
            reason_code="ai_trust_warning",
            risk_score=78,
            warning_severity="high",
            operator_note="AI observed elevated entry risk.",
        )

    async def fail_execute_budgeted_buy_order(*_args, **_kwargs):
        nonlocal executed
        executed += 1
        raise AssertionError("AI warning should block before exchange work")

    monkeypatch.setattr(
        orders.trades,
        "get_trades_for_orders",
        fake_get_trades_for_orders,
    )
    monkeypatch.setattr(orders_module, "evaluate_entry_enforcement", fake_ai_gate)
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
        {"ai_trust_enabled": True, "ai_trust_enforce_warnings": True},
    )

    assert accepted is False
    assert executed == 0


@pytest.mark.asyncio
async def test_receive_buy_order_rejects_ai_unscored_enforced_entry(
    monkeypatch,
) -> None:
    orders = Orders()
    executed = 0

    async def fake_get_trades_for_orders(_symbol: str):
        return None

    async def fake_ai_gate(_symbol, _order, _config):
        return AiTrustEntryGate(
            allowed=False,
            evaluated=True,
            provider_status="timeout",
            reason_code="ai_trust_unavailable",
        )

    async def fail_execute_budgeted_buy_order(*_args, **_kwargs):
        nonlocal executed
        executed += 1
        raise AssertionError("AI provider failure should block before exchange work")

    async def fake_close() -> None:
        return None

    monkeypatch.setattr(
        orders.trades,
        "get_trades_for_orders",
        fake_get_trades_for_orders,
    )
    monkeypatch.setattr(orders_module, "evaluate_entry_enforcement", fake_ai_gate)
    monkeypatch.setattr(
        orders,
        "_execute_budgeted_buy_order",
        fail_execute_budgeted_buy_order,
    )
    monkeypatch.setattr(orders.exchange, "close", fake_close)

    accepted = await orders.receive_buy_order(
        {
            "symbol": "BTC/USDT",
            "ordersize": 100.0,
            "baseorder": True,
            "safetyorder": False,
        },
        {"ai_trust_enabled": True, "ai_trust_enforce_warnings": True},
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
