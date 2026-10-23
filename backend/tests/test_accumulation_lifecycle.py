"""Real SQLite coverage for durable, revisioned accumulation operator intent."""

import asyncio
import json
from unittest.mock import AsyncMock

import model
import pytest
import pytest_asyncio
from service.accumulation_commands import AccumulationCommand
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_lifecycle import (
    AccumulationLifecycleService,
    AccumulationReadiness,
)
from service.accumulation_state import AccumulationConflictError
from service.lifecycle_mutation import LifecycleMutationCoordinator
from service.trading_controls import TradingControlsService
from service.trading_maintenance import TradingMaintenanceBarrier
from tortoise import Tortoise
from tortoise.exceptions import OperationalError


@pytest_asyncio.fixture
async def lifecycle_db(tmp_path, monkeypatch):
    # Each pytest case owns a new event loop; contended asyncio locks must not
    # leak across those loops. Both services still share the real coordinator.
    coordinator = LifecycleMutationCoordinator(TradingMaintenanceBarrier())
    monkeypatch.setattr(
        "service.accumulation_lifecycle.lifecycle_mutation_coordinator", coordinator
    )
    monkeypatch.setattr(
        "service.trading_controls.lifecycle_mutation_coordinator", coordinator
    )
    url = f"sqlite://{tmp_path / 'lifecycle.sqlite'}"
    await Tortoise.init(db_url=url, modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    yield url
    await Tortoise.close_connections()


async def _version(number=1):
    return await model.StrategyVersion.create(
        strategy_slug="accumulation_fixture",
        version=number,
        ir_json="{}",
        validation_json="{}",
        explanation="Lifecycle storage fixture",
    )


async def _activation(*, state="enabled", paused=False, holding=False):
    version = await _version()
    trade = (
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            lifecycle_mode="accumulation",
            accumulation_net_quantity="10",
        )
        if holding
        else None
    )
    return await model.AccumulationActivation.create(
        symbol="BTC/USDC",
        account_scope="test-account",
        strategy_version=version,
        state=state,
        explicitly_paused=paused,
        baseline_close_ms=1000,
        observations_initialized=True,
        holding=trade,
        consumption_revision=5,
        execution_guard_json='{"price":"97"}',
    )


def _command(action, revision=0, operation_id="request-1", **parameters):
    return dict(
        symbol="BTC/USDC",
        action=action,
        expected_revision=revision,
        operation_id=operation_id,
        **parameters,
    )


async def _ready(request):
    return AccumulationReadiness(
        request.account_scope, request.target_version_id, 2000, {"peak": "100"}
    )


async def _submit(service, payload):
    return await service.submit(payload, account_scope="test-account")


async def _link_sale(operation_id, *, state="completed", correct=True):
    operation = await model.AccumulationLifecycleOperation.get(
        operation_id=operation_id
    )
    placement = await model.PlacementIntent.create(
        operation_id=f"placement-{operation_id}",
        exchange_name="test",
        symbol="BTC/USDC",
        action="sell",
        side="sell",
        order_type="market",
        state=state,
        request_json=json.dumps(
            {
                "accumulation_operation_id": operation_id if correct else "other",
                "accumulation_action": operation.action,
            }
        ),
    )
    operation.placement = placement
    await operation.save()
    await model.AccumulationFillCheckpoint.create(
        placement=placement,
        activation_id=operation.activation_id,
        terminal=True,
        fees_complete=True,
        evidence_json="{}",
    )
    return placement


@pytest.mark.asyncio
async def test_staging_requires_validation_and_survives_restart(lifecycle_db):
    version = await _version()
    service = AccumulationLifecycleService()
    args = dict(
        symbol="btc_usdc",
        account_scope="test-account",
        strategy_version_id=version.id,
        source="asap",
        operation_id="activate-1",
    )
    staged = await service.stage_activation(**args)
    assert staged.state == "validating" and staged.status == "pending"
    assert await model.OpenTrades.all().count() == 0
    with pytest.raises(AccumulationStateError, match="not connected"):
        await service.complete_rebase("activate-1", account_scope="test-account")
    await Tortoise.close_connections()
    await Tortoise.init(db_url=lifecycle_db, modules={"models": ["model"]})
    assert await service.stage_activation(**args) == staged
    service = AccumulationLifecycleService(_ready)
    enabled = await service.complete_rebase("activate-1", account_scope="test-account")
    assert enabled.state == "enabled" and enabled.revision == 2
    activation = await model.AccumulationActivation.get(id=staged.activation_id)
    assert activation.observation_epoch == 1
    assert activation.baseline_close_ms == 2000
    assert not activation.explicitly_paused
    assert await model.OpenTrades.all().count() == 0
    assert (await service.stage_activation(**args)).status == "applied"


@pytest.mark.asyncio
async def test_staging_rejects_other_plugins_existing_holdings_and_unknown_versions(
    lifecycle_db,
):
    version = await _version()
    service = AccumulationLifecycleService()
    args = dict(
        symbol="BTC/USDC",
        account_scope="test-account",
        strategy_version_id=version.id,
        source="asap",
        operation_id="activate-1",
    )
    with pytest.raises(AccumulationStateError, match="ASAP or CSV"):
        await service.stage_activation(**{**args, "source": "sym_signals"})
    with pytest.raises(AccumulationStateError, match="does not exist"):
        await service.stage_activation(**{**args, "strategy_version_id": 999})
    await model.OpenTrades.create(symbol="BTC/USDC")
    with pytest.raises(AccumulationConflictError, match="cannot be converted"):
        await service.stage_activation(**args)
    assert await model.AccumulationActivation.all().count() == 0


@pytest.mark.asyncio
async def test_pause_is_idempotent_and_rejects_stale_or_reused_requests(lifecycle_db):
    activation = await _activation()
    service = AccumulationLifecycleService()
    payload = _command("pause")
    paused = await _submit(service, payload)
    assert paused.state == "paused" and paused.status == "applied"
    assert await _submit(service, payload) == paused
    with pytest.raises(AccumulationConflictError, match="different request"):
        await _submit(service, _command("resume", revision=1))
    with pytest.raises(AccumulationConflictError, match="Stale"):
        await _submit(service, _command("resume", operation_id="request-2"))
    with pytest.raises(AccumulationConflictError, match="different request"):
        await service.submit(payload, account_scope="another-account")
    await activation.refresh_from_db()
    assert activation.revision == 1 and activation.explicitly_paused
    assert activation.execution_guard_json == '{"price":"97"}'
    assert activation.consumption_revision == 5


@pytest.mark.asyncio
async def test_concurrent_dashboards_cannot_overwrite_a_revision(lifecycle_db):
    await _activation()
    service = AccumulationLifecycleService()
    results = await asyncio.gather(
        _submit(service, _command("pause", operation_id="tab-1")),
        _submit(service, _command("pause", operation_id="tab-2")),
        return_exceptions=True,
    )
    assert sum(isinstance(result, AccumulationConflictError) for result in results) == 1
    assert await model.AccumulationLifecycleOperation.all().count() == 1


@pytest.mark.asyncio
async def test_command_journal_failure_rolls_back_state(lifecycle_db, monkeypatch):
    activation = await _activation()
    monkeypatch.setattr(
        model.AccumulationLifecycleOperation,
        "create",
        AsyncMock(side_effect=OperationalError("disk failure")),
    )
    with pytest.raises(OperationalError):
        await _submit(AccumulationLifecycleService(), _command("pause"))
    await activation.refresh_from_db()
    assert activation.state == "enabled" and activation.revision == 0


@pytest.mark.asyncio
async def test_completion_retries_preserve_newer_operator_intent(lifecycle_db):
    activation = await _activation(state="paused", paused=True)
    validator = AsyncMock(side_effect=_ready)
    service = AccumulationLifecycleService(validator)
    await _submit(service, _command("resume"))
    enabled = await service.complete_rebase("request-1", account_scope="test-account")
    paused = await _submit(
        service, _command("pause", revision=enabled.revision, operation_id="pause-1")
    )
    assert (
        await service.complete_rebase("request-1", account_scope="test-account")
        == enabled
    )
    assert (
        await service.complete_settlement("pause-1", account_scope="test-account")
        == paused
    )
    with pytest.raises(AccumulationStateError, match="Account scope"):
        await service.complete_rebase("request-1", account_scope="other-account")
    await activation.refresh_from_db()
    assert activation.state == "paused" and activation.revision == paused.revision
    assert validator.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["wrong_account", "wrong_version", "old_baseline", "write"]
)
async def test_failed_rebase_keeps_old_pin_observations_and_execution_guard(
    lifecycle_db, monkeypatch, failure
):
    activation = await _activation()
    original_version = activation.strategy_version_id
    target = await _version(2)

    async def invalid_ready(request):
        return AccumulationReadiness(
            "other" if failure == "wrong_account" else request.account_scope,
            original_version
            if failure == "wrong_version"
            else request.target_version_id,
            999 if failure == "old_baseline" else 2000,
            {"peak": "100"},
        )

    service = AccumulationLifecycleService(invalid_ready)
    await _submit(service, _command("switch_strategy", target_version_id=target.id))
    if failure == "write":
        monkeypatch.setattr(
            model.AccumulationStrategyState,
            "create",
            AsyncMock(side_effect=OperationalError("disk failure")),
        )
    with pytest.raises((AccumulationStateError, OperationalError)):
        await service.complete_rebase("request-1", account_scope="test-account")
    await activation.refresh_from_db()
    assert activation.state == "switching" and activation.revision == 1
    assert activation.strategy_version_id == original_version
    assert activation.observation_epoch == 0 and activation.baseline_close_ms == 1000
    assert activation.consumption_revision == 5
    assert activation.execution_guard_json == '{"price":"97"}'
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id="request-1")
    ).status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "placement_state",
    ["indeterminate", "quarantined", "restored_quarantined", "unexpected_state"],
)
async def test_pause_latches_before_reconciliation_and_resume_waits(
    lifecycle_db, placement_state
):
    activation = await _activation()
    intent = await model.PlacementIntent.create(
        operation_id="buy-1",
        exchange_name="test",
        symbol="BTC/USDC",
        action="buy",
        side="buy",
        order_type="market",
        state=placement_state,
    )
    service = AccumulationLifecycleService(_ready)
    paused = await _submit(service, _command("pause"))
    assert paused.state == "paused" and paused.status == "pending"
    await activation.refresh_from_db()
    assert activation.explicitly_paused
    with pytest.raises(AccumulationConflictError, match="reconciliation"):
        await service.complete_settlement("request-1", account_scope="test-account")
    with pytest.raises(AccumulationConflictError, match="pending"):
        await _submit(service, _command("resume", revision=1, operation_id="resume-1"))
    intent.state = "completed"
    await intent.save()
    settled = await service.complete_settlement(
        "request-1", account_scope="test-account"
    )
    resumed = await _submit(
        service, _command("resume", revision=settled.revision, operation_id="resume-1")
    )
    assert resumed.state == "validating"
    enabled = await service.complete_rebase("resume-1", account_scope="test-account")
    assert enabled.state == "enabled"
    await activation.refresh_from_db()
    assert activation.baseline_close_ms == 2000
    assert activation.consumption_revision == 5


@pytest.mark.asyncio
async def test_switch_preserves_old_pin_until_validation_and_pause_can_supersede(
    lifecycle_db,
):
    activation = await _activation()
    target = await _version(2)
    service = AccumulationLifecycleService(_ready)
    switched = await _submit(
        service, _command("switch_strategy", target_version_id=target.id)
    )
    await activation.refresh_from_db()
    assert activation.strategy_version_id != target.id
    paused = await _submit(
        service, _command("pause", revision=switched.revision, operation_id="pause-1")
    )
    assert paused.state == "paused"
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id="request-1")
    ).status == "cancelled"
    with pytest.raises(AccumulationConflictError, match="no longer current"):
        await service.complete_rebase("request-1", account_scope="test-account")
    switched = await _submit(
        service,
        _command(
            "switch_strategy",
            revision=paused.revision,
            operation_id="switch-2",
            target_version_id=target.id,
        ),
    )
    result = await service.complete_rebase("switch-2", account_scope="test-account")
    assert result.state == "paused"
    await activation.refresh_from_db()
    assert activation.strategy_version_id == target.id
    assert activation.execution_guard_json == '{"price":"97"}'
    assert activation.consumption_revision == 5


@pytest.mark.asyncio
async def test_pause_during_readiness_invalidates_the_validation_result(lifecycle_db):
    await _activation(state="paused", paused=True)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_ready(request):
        entered.set()
        await release.wait()
        return await _ready(request)

    service = AccumulationLifecycleService(slow_ready)
    await _submit(service, _command("resume"))
    validation = asyncio.create_task(
        service.complete_rebase("request-1", account_scope="test-account")
    )
    await entered.wait()
    paused = await _submit(
        service, _command("pause", revision=1, operation_id="pause-1")
    )
    release.set()
    with pytest.raises(AccumulationConflictError):
        await validation
    assert (await model.AccumulationActivation.get(symbol="BTC/USDC")).state == "paused"
    assert paused.revision == 2


@pytest.mark.asyncio
async def test_concurrent_rebase_completions_create_only_one_observation_epoch(
    lifecycle_db,
):
    activation = await _activation(state="paused", paused=True)
    both_entered = asyncio.Event()
    entered = 0

    async def racing_ready(request):
        nonlocal entered
        entered += 1
        if entered == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=2)
        return await _ready(request)

    service = AccumulationLifecycleService(racing_ready)
    await _submit(service, _command("resume"))
    first, second = await asyncio.gather(
        service.complete_rebase("request-1", account_scope="test-account"),
        service.complete_rebase("request-1", account_scope="test-account"),
    )
    assert first == second
    await activation.refresh_from_db()
    assert activation.observation_epoch == 1 and activation.revision == 2
    assert await model.AccumulationStrategyState.all().count() == 1


@pytest.mark.asyncio
async def test_expired_opportunity_keeps_pause_pending_until_slot_reconciled(
    lifecycle_db,
):
    activation = await _activation()
    opportunity = await model.AccumulationOpportunity.create(
        activation=activation,
        generation=activation.generation,
        strategy_version_id=activation.strategy_version_id,
        observation_epoch=0,
        signal_close_ms=1,
        expires_at_ms=2,
        signal_price="100",
        signal_atr="2",
        status="expired",
        unresolved_slot=activation.id,
    )
    service = AccumulationLifecycleService()
    assert (await _submit(service, _command("pause"))).status == "pending"
    with pytest.raises(AccumulationConflictError, match="reconciliation"):
        await service.complete_settlement("request-1", account_scope="test-account")
    opportunity.unresolved_slot = None
    await opportunity.save()
    assert (
        await service.complete_settlement("request-1", account_scope="test-account")
    ).status == "applied"


@pytest.mark.asyncio
async def test_full_close_stays_closing_until_accounted_empty_then_requires_reactivation(
    lifecycle_db,
):
    activation = await _activation(holding=True)
    generation = activation.generation
    service = AccumulationLifecycleService(_ready)
    closing = await _submit(service, _command("close"))
    assert closing.state == "closing"
    with pytest.raises(AccumulationConflictError, match="accounting"):
        await service.complete_settlement("request-1", account_scope="test-account")
    await _link_sale("request-1")
    await model.OpenTrades.filter(id=activation.holding_id).update(
        accumulation_net_quantity="0.000001"
    )
    with pytest.raises(AccumulationConflictError, match="remaining holding or dust"):
        await service.complete_settlement("request-1", account_scope="test-account")
    await model.OpenTrades.filter(id=activation.holding_id).delete()
    stopped = await service.complete_settlement(
        "request-1", account_scope="test-account"
    )
    assert stopped.state == "stopped"
    assert (await _submit(service, _command("close"))).state == "stopped"
    with pytest.raises(AccumulationConflictError, match="explicitly paused"):
        await _submit(
            service,
            _command("resume", revision=stopped.revision, operation_id="resume-1"),
        )
    await _submit(
        service,
        _command("reactivate", revision=stopped.revision, operation_id="reactivate-1"),
    )
    await service.complete_rebase("reactivate-1", account_scope="test-account")
    await activation.refresh_from_db()
    assert activation.generation != generation
    assert activation.state == "enabled"
    assert activation.consumption_revision == 0
    assert activation.execution_guard_json is None


@pytest.mark.asyncio
@pytest.mark.parametrize("paused", [True, False])
async def test_partial_sale_restores_prior_pause_only_with_matching_completed_intent(
    lifecycle_db, paused
):
    activation = await _activation(
        holding=True, state="paused" if paused else "enabled", paused=paused
    )
    service = AccumulationLifecycleService()
    result = await _submit(service, _command("sell_partial", quantity="2"))
    assert result.state == "selling_partial"
    placement = await _link_sale("request-1", correct=False)
    with pytest.raises(AccumulationConflictError, match="authorize"):
        await service.complete_settlement("request-1", account_scope="test-account")
    placement.request_json = json.dumps(
        {
            "accumulation_operation_id": "request-1",
            "accumulation_action": "sell_partial",
        }
    )
    await placement.save()
    await model.OpenTrades.filter(id=activation.holding_id).update(
        accumulation_net_quantity="8"
    )
    result = await service.complete_settlement(
        "request-1", account_scope="test-account"
    )
    assert result.state == ("paused" if paused else "enabled")
    await activation.refresh_from_db()
    assert activation.explicitly_paused is paused


@pytest.mark.asyncio
async def test_partial_sale_rejects_full_or_unknown_inventory(lifecycle_db):
    activation = await _activation(holding=True)
    service = AccumulationLifecycleService()
    with pytest.raises(AccumulationStateError, match="Full close"):
        await _submit(service, _command("sell_partial", quantity="10"))
    await model.OpenTrades.filter(id=activation.holding_id).update(
        accumulation_net_quantity=None
    )
    with pytest.raises(AccumulationStateError, match="decimal string"):
        await _submit(service, _command("sell_partial", quantity="2"))
    assert await model.AccumulationLifecycleOperation.all().count() == 0


@pytest.mark.asyncio
async def test_legacy_pause_resume_cannot_bypass_revisioned_activation(lifecycle_db):
    activation = await _activation(holding=True)
    controls = TradingControlsService()
    assert (await controls.pause_mission("BTC/USDC", {})).status == "lifecycle_required"
    assert (await controls.resume_mission("BTC/USDC")).status == "lifecycle_required"
    await activation.refresh_from_db()
    assert activation.revision == 0 and activation.state == "enabled"


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_revision": True},
        {"expected_revision": -1},
        {"operation_id": ""},
        {"unexpected": True},
        {"action": "sell"},
        {"action": "sell_partial", "quantity": 1.0},
        {"action": "switch_strategy", "target_version_id": True},
    ],
)
def test_command_parser_rejects_ambiguous_or_unversioned_mutations(overrides):
    with pytest.raises((ValueError, TypeError)):
        AccumulationCommand.from_dict({**_command("pause"), **overrides})


@pytest.mark.asyncio
async def test_close_retry_preserves_prior_operation_and_exact_retry_identity(
    lifecycle_db,
):
    activation = await _activation(holding=True)
    service = AccumulationLifecycleService()
    initial = await _submit(service, _command("close"))
    placement = await _link_sale("request-1")
    request = _command(
        "retry_close", initial.revision, "retry-1", previous_operation_id="request-1"
    )
    result = await _submit(service, request)
    assert result.state == "closing" and result.status == "pending"
    old = await model.AccumulationLifecycleOperation.get(operation_id="request-1")
    assert old.status == "continued" and old.placement_id == placement.id
    assert old.result_state == "closing"
    assert await _submit(service, request) == result
    assert (await _submit(service, _command("close"))).status == "continued"
    with pytest.raises(AccumulationConflictError, match="different request"):
        await _submit(service, {**request, "previous_operation_id": "another"})
    await activation.refresh_from_db()
    assert activation.holding_id is not None and activation.consumption_revision == 5
    assert activation.execution_guard_json == '{"price":"97"}'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "submitting",
        "accepted",
        "persisted",
        "rejected",
        "quarantined",
        "fees",
        "terminal",
        "checkpoint",
        "context",
        "other_pending",
        "empty",
        "wrong_state",
        "stale",
    ],
)
async def test_close_retry_requires_current_fully_settled_sale(lifecycle_db, fault):
    activation = await _activation(holding=True)
    service = AccumulationLifecycleService()
    initial = await _submit(service, _command("close"))
    placement = await _link_sale("request-1")
    request = _command(
        "retry_close", initial.revision, "retry-1", previous_operation_id="request-1"
    )
    if fault in {"submitting", "accepted", "persisted", "rejected", "quarantined"}:
        placement.state = fault
        await placement.save()
    elif fault == "unknown":
        request["previous_operation_id"] = "missing"
    elif fault in {"fees", "terminal", "checkpoint"}:
        checkpoint = await model.AccumulationFillCheckpoint.get(placement=placement)
        if fault == "checkpoint":
            await checkpoint.delete()
        else:
            setattr(
                checkpoint, "fees_complete" if fault == "fees" else "terminal", False
            )
            await checkpoint.save()
    elif fault == "context":
        placement.request_json = "{}"
        await placement.save()
    elif fault == "other_pending":
        await model.PlacementIntent.create(
            operation_id="unknown-placement",
            symbol=activation.symbol,
            exchange_name="test",
            action="buy",
            side="buy",
            order_type="limit",
            state="indeterminate",
        )
    elif fault == "empty":
        await model.OpenTrades.filter(id=activation.holding_id).update(
            accumulation_net_quantity="0"
        )
    elif fault == "wrong_state":
        await model.AccumulationActivation.filter(id=activation.id).update(
            state="paused"
        )
    else:
        request["expected_revision"] -= 1
    with pytest.raises(AccumulationStateError):
        await _submit(service, request)
    assert not await model.AccumulationLifecycleOperation.filter(
        operation_id="retry-1"
    ).exists()
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id="request-1")
    ).status == "pending"


@pytest.mark.asyncio
async def test_two_dashboards_cannot_authorize_two_remainder_sales(lifecycle_db):
    await _activation(holding=True)
    service = AccumulationLifecycleService()
    initial = await _submit(service, _command("close"))
    await _link_sale("request-1")
    results = await asyncio.gather(
        *(
            _submit(
                service,
                _command(
                    "retry_close",
                    initial.revision,
                    name,
                    previous_operation_id="request-1",
                ),
            )
            for name in ("retry-a", "retry-b")
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, AccumulationConflictError) for result in results) == 1
    assert (
        await model.AccumulationLifecycleOperation.filter(status="pending").count() == 1
    )


@pytest.mark.asyncio
async def test_close_retry_rollback_preserves_original_pending_command(
    lifecycle_db, monkeypatch
):
    await _activation(holding=True)
    service = AccumulationLifecycleService()
    initial = await _submit(service, _command("close"))
    await _link_sale("request-1")
    monkeypatch.setattr(
        model.AccumulationLifecycleOperation,
        "create",
        AsyncMock(side_effect=OperationalError("rollback")),
    )
    with pytest.raises(OperationalError):
        await _submit(
            service,
            _command(
                "retry_close",
                initial.revision,
                "retry-1",
                previous_operation_id="request-1",
            ),
        )
    old = await model.AccumulationLifecycleOperation.get(operation_id="request-1")
    assert old.status == "pending"
    assert (
        await model.AccumulationActivation.get(id=old.activation_id)
    ).revision == initial.revision


@pytest.mark.parametrize(
    "change",
    [
        {"previous_operation_id": ""},
        {"previous_operation_id": None},
        {"quantity": "1"},
        {"target_version_id": 1},
    ],
)
def test_close_retry_rejects_ambiguous_transport_fields(change):
    with pytest.raises(AccumulationStateError):
        AccumulationCommand.from_dict(
            {**_command("retry_close", previous_operation_id="prior"), **change}
        )


def test_legacy_command_retry_serialization_remains_unchanged():
    encoded = json.loads(
        AccumulationCommand.from_dict(_command("close")).request_json("account")
    )
    assert "previous_operation_id" not in encoded
