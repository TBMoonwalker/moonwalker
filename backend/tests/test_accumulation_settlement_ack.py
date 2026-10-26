"""Acknowledgement cannot replay a committed sale or clear remaining dust."""

import asyncio
import json
from types import SimpleNamespace

import model
import pytest
import pytest_asyncio
from service.accumulation_accounting import _inventory
from service.accumulation_repair import AccumulationOrderRepair
from service.accumulation_state import AccumulationConflictError
from service.accumulation_status import get_accumulation_status
from service.lifecycle_mutation import LifecycleMutationCoordinator
from service.trading_maintenance import TradingMaintenanceBarrier
from tortoise import Tortoise


@pytest_asyncio.fixture
async def settlement_db(tmp_path, monkeypatch):
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'ack.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    monkeypatch.setattr(
        "service.accumulation_settlement_ack.lifecycle_mutation_coordinator",
        LifecycleMutationCoordinator(TradingMaintenanceBarrier()),
    )
    yield
    await Tortoise.close_connections()


async def fixture_sale(quantity="0.00000001", action="close"):
    version = await model.StrategyVersion.create(
        strategy_slug="ack",
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="fixture",
    )
    holding = (
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            lifecycle_mode="accumulation",
            accumulation_net_quantity=quantity,
            accumulation_remaining_cost="1",
            accumulation_contributed_quote="10",
            accumulation_disposal_proceeds="11",
            accumulation_fees_json='{"totals":{"USDC":"1"},"pending_reports":0}',
        )
        if quantity != "0"
        else None
    )
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC",
        strategy_version=version,
        account_scope="old-account",
        holding=holding,
        state="closing" if action == "close" else "paused",
        explicitly_paused=True,
        revision=5,
        observations_initialized=True,
        consumption_revision=3,
        execution_guard_json='{"kept":true}',
    )
    placement = await model.PlacementIntent.create(
        operation_id="settled-sale",
        symbol=activation.symbol,
        exchange_name="binance",
        side="sell",
        action="sell",
        order_type="limit",
        state="completed",
    )
    sale = await model.AccumulationLifecycleOperation.create(
        activation=activation,
        operation_id="sale-command",
        action=action,
        status="quarantined",
        placement=placement,
        request_json="{}",
        previous_state="enabled",
        previous_paused=False,
        result_state=activation.state,
        result_revision=4,
    )
    inventory = json.loads(_inventory(holding).serialize())
    if holding is None:
        inventory.update(
            contributed_quote="10", disposal_proceeds="11", fees={"USDC": "1"}
        )
    checkpoint = await model.AccumulationFillCheckpoint.create(
        activation=activation,
        placement=placement,
        terminal=True,
        fees_complete=True,
        filled="1",
        quote_cost="11",
        evidence_json="{}",
        inventory_json=json.dumps(inventory),
    )
    payload = {
        "symbol": activation.symbol,
        "action": "acknowledge_settlement",
        "operation_id": "ack-command",
        "expected_revision": 5,
        "previous_operation_id": sale.operation_id,
    }
    # No config, exchange, wallet, placement or cancellation interface exists.
    return (
        activation,
        holding,
        sale,
        checkpoint,
        AccumulationOrderRepair(SimpleNamespace()),
        payload,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quantity,action,state,status",
    [
        ("0.00000001", "close", "closing", "reconciled"),
        ("0", "close", "stopped", "applied"),
        ("0.5", "sell_partial", "paused", "applied"),
    ],
)
async def test_acknowledgement_preserves_money_guards_and_latches(
    settlement_db, quantity, action, state, status
):
    activation, holding, sale, _, repair, payload = await fixture_sale(quantity, action)
    original = _inventory(holding)
    detail = await get_accumulation_status(activation.symbol, wait_reasons={})
    assert detail["settled_commands"][0]["operation_id"] == sale.operation_id
    results = await asyncio.gather(*(repair.submit(payload) for _ in range(8)))
    assert all(row == results[0] for row in results)
    await activation.refresh_from_db()
    await sale.refresh_from_db()
    assert activation.revision == 6 and activation.explicitly_paused
    assert activation.state == state and sale.status == status
    assert activation.account_scope == "old-account"
    assert (
        activation.consumption_revision == 3
        and activation.execution_guard_json == '{"kept":true}'
    )
    if holding:
        await holding.refresh_from_db()
    assert _inventory(holding) == original
    assert await model.PlacementIntent.all().count() == 1
    assert await model.TradeExecutions.all().count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "fees",
        "terminal",
        "inventory",
        "placement",
        "revision",
        "paused",
        "partial_zero",
    ],
)
async def test_incomplete_or_changed_settlement_cannot_be_acknowledged(
    settlement_db, fault
):
    activation, holding, sale, checkpoint, repair, payload = await fixture_sale(
        "0" if fault == "partial_zero" else "0.5",
        "sell_partial" if fault == "partial_zero" else "close",
    )
    if fault in {"fees", "terminal"}:
        setattr(checkpoint, "fees_complete" if fault == "fees" else "terminal", False)
        await checkpoint.save()
    elif fault == "inventory":
        holding.accumulation_net_quantity = "0.4"
        await holding.save()
    elif fault == "placement":
        await model.PlacementIntent.filter(id=sale.placement_id).update(
            state="accepted"
        )
    elif fault == "revision":
        payload["expected_revision"] = 4
    elif fault == "paused":
        activation.explicitly_paused = False
        await activation.save()
    with pytest.raises(AccumulationConflictError):
        await repair.submit(payload)
    await sale.refresh_from_db()
    assert sale.status == "quarantined"
    assert await model.AccumulationLifecycleOperation.all().count() == 1
