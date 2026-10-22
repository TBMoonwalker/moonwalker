"""Real SQLite proof that retiring restored intent cannot replay exchange work."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import model
import pytest
import pytest_asyncio
from service.accumulation_import import parse_accumulation_csv
from service.accumulation_lifecycle import AccumulationLifecycleService
from service.accumulation_repair import AccumulationOrderRepair
from service.accumulation_staged_entry import StagedEntryCommand, stage_entry_command
from service.accumulation_state import AccumulationConflictError
from service.accumulation_status import get_accumulation_status
from service.lifecycle_mutation import LifecycleMutationCoordinator
from service.trading_maintenance import TradingMaintenanceBarrier
from tortoise import Tortoise


@pytest_asyncio.fixture
async def retired_db(tmp_path, monkeypatch):
    url = f"sqlite://{tmp_path / 'retirement.sqlite'}"
    await Tortoise.init(db_url=url, modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    coordinator = LifecycleMutationCoordinator(TradingMaintenanceBarrier())
    for name in ("accumulation_repair", "accumulation_lifecycle"):
        monkeypatch.setattr(
            f"service.{name}.lifecycle_mutation_coordinator", coordinator
        )
    yield url
    await Tortoise.close_connections()


async def setup_intent(
    action="switch_strategy", *, initialized=True, state="switching"
):
    version = await model.StrategyVersion.create(
        strategy_slug="retirement_fixture",
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="fixture",
    )
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC",
        account_scope="same-account",
        strategy_version=version,
        state=state,
        explicitly_paused=True,
        revision=5,
        observations_initialized=initialized,
        baseline_close_ms=1000 if initialized else None,
        consumption_revision=3 if initialized else 0,
        execution_guard_json='{"retained":"guard"}' if initialized else None,
    )
    request = {"source": "asap"}
    target = await model.AccumulationLifecycleOperation.create(
        activation=activation,
        operation_id="old-intent",
        action=action,
        status="quarantined",
        previous_state="enabled",
        previous_paused=False,
        result_state=state,
        result_revision=4,
        reason="restore_validation_required",
        request_json=json.dumps(request),
        target_version=version,
    )
    config = {"exchange": "binance", "dry_run": False, "market": "spot"}
    # No exchange API exists on this adapter. Any network/order call fails the test.
    adapter = SimpleNamespace(
        config=lambda: config, account_scope=AsyncMock(return_value="same-account")
    )
    payload = {
        "symbol": activation.symbol,
        "action": "retire_command",
        "operation_id": "retirement-1",
        "expected_revision": activation.revision,
        "previous_operation_id": target.operation_id,
    }
    return activation, target, adapter, payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        "pause",
        "resume",
        "reactivate",
        "switch_strategy",
        "sell_partial",
        "close",
        "retry_close",
    ],
)
async def test_retirement_preserves_inventory_pins_guards_and_close_latch(
    retired_db, action
):
    activation, target, adapter, payload = await setup_intent(action)
    holding = await model.OpenTrades.create(
        symbol=activation.symbol,
        lifecycle_mode="accumulation",
        accumulation_net_quantity="0.100000000000000001",
        accumulation_remaining_cost=None,
        accumulation_fees_json='{"totals":{},"pending_reports":1}',
    )
    activation.holding = holding
    if action in {"close", "retry_close"}:
        activation.state = "closing"
    await activation.save()
    identity = (
        activation.generation,
        activation.strategy_version_id,
        activation.baseline_close_ms,
        activation.observation_epoch,
        activation.consumption_revision,
        activation.execution_guard_json,
    )
    with pytest.raises(AccumulationConflictError, match="Retire or reconcile"):
        await AccumulationLifecycleService().submit(
            {
                "symbol": activation.symbol,
                "action": "pause",
                "operation_id": "no-bypass",
                "expected_revision": 5,
            },
            account_scope="same-account",
        )
    result = await AccumulationOrderRepair(adapter).submit(payload)
    assert result.status == "applied"
    assert result.state == (
        "closing" if action in {"close", "retry_close"} else "paused"
    )
    await activation.refresh_from_db()
    await target.refresh_from_db()
    assert activation.explicitly_paused and activation.revision == 6
    assert target.status == "cancelled" and target.reason == "restore_intent_retired"
    assert identity == (
        activation.generation,
        activation.strategy_version_id,
        activation.baseline_close_ms,
        activation.observation_epoch,
        activation.consumption_revision,
        activation.execution_guard_json,
    )
    assert (
        await model.OpenTrades.get(id=holding.id)
    ).accumulation_net_quantity == "0.100000000000000001"
    assert (
        await model.OpenTrades.get(id=holding.id)
    ).accumulation_remaining_cost is None
    assert not await model.PlacementIntent.exists()
    assert not await model.AccumulationLifecycleOperation.filter(
        status="pending"
    ).exists()
    assert await AccumulationOrderRepair(adapter).submit(payload) == result
    with pytest.raises(AccumulationConflictError):
        await AccumulationOrderRepair(adapter).submit(
            {**payload, "previous_operation_id": "another-intent"}
        )
    await Tortoise.close_connections()
    await Tortoise.init(db_url=retired_db, modules={"models": ["model"]})
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id=target.operation_id)
    ).status == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["retry_entry", "correct_import", "abandon_entry"])
async def test_retired_csv_declaration_can_be_explicitly_validated_corrected_or_abandoned(
    retired_db, action
):
    activation, target, adapter, payload = await setup_intent(
        "activate", initialized=False, state="validating"
    )
    declaration = parse_accumulation_csv(
        "1970-01-02;BTC/USDC;60;0.1", "USDC", now_ms=100000000
    )[0]
    target.request_json = json.dumps(
        {"source": "csv", "imported_inventory": declaration.to_dict()}
    )
    await target.save()
    original = target.request_json
    await AccumulationOrderRepair(adapter).submit(payload)
    await activation.refresh_from_db()
    command = {
        "symbol": activation.symbol,
        "action": action,
        "operation_id": "new-entry-decision",
        "expected_revision": activation.revision,
        "previous_operation_id": target.operation_id,
    }
    if action == "correct_import":
        command["csv_content"] = "1970-01-02;BTC/USDC;65;0.2"
    result = await stage_entry_command(
        StagedEntryCommand.from_dict(command, now_ms=100000000),
        account_scope="same-account",
    )
    await target.refresh_from_db()
    assert target.request_json == original
    assert (
        result.state
        == {
            "retry_entry": "validating",
            "correct_import": "validating",
            "abandon_entry": "stopped",
        }[action]
    )
    if action == "correct_import":
        assert (
            await model.AccumulationActivation.get(id=activation.id)
        ).explicitly_paused
    assert not await model.OpenTrades.exists()
    assert not await model.PlacementIntent.exists()


@pytest.mark.asyncio
async def test_retired_close_can_only_be_sold_by_a_new_explicit_retry(retired_db):
    activation, target, adapter, payload = await setup_intent("close", state="closing")
    holding = await model.OpenTrades.create(
        symbol=activation.symbol,
        lifecycle_mode="accumulation",
        accumulation_net_quantity="1",
    )
    activation.holding = holding
    await activation.save()
    await AccumulationOrderRepair(adapter).submit(payload)
    await activation.refresh_from_db()
    # The predecessor must remain available beyond the recent-requests page.
    for index in range(25):
        await model.AccumulationLifecycleOperation.create(
            activation=activation,
            operation_id=f"old-receipt-{index}",
            action="pause",
            request_json="{}",
            status="applied",
            previous_state="paused",
            previous_paused=True,
            result_state="paused",
            result_revision=1,
        )
    detail = await get_accumulation_status(activation.symbol, wait_reasons={})
    assert detail["close_predecessor"]["operation_id"] == target.operation_id
    assert all(
        row["operation_id"] != target.operation_id for row in detail["operations"]
    )
    result = await AccumulationLifecycleService().submit(
        {
            "symbol": activation.symbol,
            "action": "retry_close",
            "operation_id": "fresh-sale-intent",
            "expected_revision": activation.revision,
            "previous_operation_id": target.operation_id,
        },
        account_scope="same-account",
    )
    assert result.status == "pending" and result.state == "closing"
    assert not await model.PlacementIntent.exists()
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id=target.operation_id)
    ).status == "continued"


@pytest.mark.asyncio
@pytest.mark.parametrize("attached", [False, True])
async def test_retirement_cannot_clear_attached_or_unresolved_orders(
    retired_db, attached
):
    activation, target, adapter, payload = await setup_intent()
    placement = await model.PlacementIntent.create(
        operation_id="unresolved",
        symbol=activation.symbol,
        exchange_name="binance",
        side="buy",
        action="buy",
        order_type="limit",
        state="restored_quarantined",
    )
    if attached:
        target.placement = placement
        await target.save()
    with pytest.raises(AccumulationConflictError):
        await AccumulationOrderRepair(adapter).submit(payload)
    assert (await model.AccumulationActivation.get(id=activation.id)).revision == 5
    assert (
        await model.PlacementIntent.get(id=placement.id)
    ).state == "restored_quarantined"
    assert await model.AccumulationLifecycleOperation.all().count() == 1


@pytest.mark.asyncio
async def test_concurrent_dashboards_can_retire_an_intent_only_once(retired_db):
    activation, target, adapter, payload = await setup_intent()
    results = await asyncio.gather(
        *[
            AccumulationOrderRepair(adapter).submit(
                {**payload, "operation_id": f"client-{index}"}
            )
            for index in range(8)
        ],
        return_exceptions=True,
    )
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert all(
        not isinstance(result, BaseException)
        or isinstance(result, AccumulationConflictError)
        for result in results
    )
    assert (
        await model.AccumulationLifecycleOperation.filter(
            action="retire_command"
        ).count()
        == 1
    )
    assert (await model.AccumulationActivation.get(id=activation.id)).revision == 6


@pytest.mark.asyncio
async def test_receipt_failure_rolls_back_intent_and_activation(
    retired_db, monkeypatch
):
    activation, target, adapter, payload = await setup_intent()
    monkeypatch.setattr(
        model.AccumulationLifecycleOperation,
        "create",
        AsyncMock(side_effect=RuntimeError("receipt failed")),
    )
    with pytest.raises(RuntimeError, match="receipt failed"):
        await AccumulationOrderRepair(adapter).submit(payload)
    await activation.refresh_from_db()
    await target.refresh_from_db()
    assert activation.revision == 5 and activation.state == "switching"
    assert target.status == "quarantined"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation", ["stale", "account", "unpaused", "pending", "unlinked_inventory"]
)
async def test_retirement_rejects_stale_account_or_ownership_changes(
    retired_db, mutation
):
    activation, target, adapter, payload = await setup_intent()
    if mutation == "stale":
        payload["expected_revision"] = 4
    elif mutation == "account":
        adapter.account_scope.return_value = "different-account"
    elif mutation == "unpaused":
        await model.AccumulationActivation.filter(id=activation.id).update(
            explicitly_paused=False
        )
    elif mutation == "pending":
        await model.AccumulationLifecycleOperation.create(
            activation=activation,
            operation_id="new-work",
            action="pause",
            request_json="{}",
            status="pending",
            previous_state="paused",
            previous_paused=True,
            result_state="paused",
            result_revision=5,
        )
    else:
        await model.OpenTrades.create(
            symbol=activation.symbol,
            lifecycle_mode="accumulation",
            accumulation_net_quantity="1",
        )
    with pytest.raises(AccumulationConflictError):
        await AccumulationOrderRepair(adapter).submit(payload)
    await target.refresh_from_db()
    assert target.status == "quarantined"
    assert not await model.AccumulationLifecycleOperation.filter(
        action="retire_command"
    ).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates",
    [
        {"quantity": "1"},
        {"expected_revision": True},
        {"symbol": None},
        {"previous_operation_id": ""},
    ],
)
async def test_retirement_rejects_ambiguous_transport_fields(retired_db, updates):
    from service.accumulation_contracts import AccumulationStateError

    activation, target, adapter, payload = await setup_intent()
    with pytest.raises(AccumulationStateError):
        await AccumulationOrderRepair(adapter).submit({**payload, **updates})
    assert (await model.AccumulationActivation.get(id=activation.id)).revision == 5
