"""An operator declaration is explicit, auditable and never account-ID inference."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import model
import pytest
import pytest_asyncio
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_import import parse_accumulation_csv
from service.accumulation_repair import AccumulationOrderRepair
from service.accumulation_staged_entry import StagedEntryCommand, stage_entry_command
from service.accumulation_state import AccumulationConflictError
from service.lifecycle_mutation import LifecycleMutationCoordinator
from service.trading_maintenance import TradingMaintenanceBarrier
from tortoise import Tortoise

NOW = 1_700_000_000_000


@pytest_asyncio.fixture
async def ownership_db(tmp_path, monkeypatch):
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'ownership.sqlite'}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()
    coordinator = LifecycleMutationCoordinator(TradingMaintenanceBarrier())
    for module in (
        "accumulation_ownership_declaration",
        "accumulation_lifecycle",
    ):
        monkeypatch.setattr(
            f"service.{module}.lifecycle_mutation_coordinator", coordinator
        )
    yield
    await Tortoise.close_connections()


async def declaration_fixture(*, staged=False, state="enabled"):
    imported = parse_accumulation_csv(
        "2020-01-01;BTC/USDC;10;1.000000000000000001", "USDC", now_ms=NOW
    )[0]
    version = await model.StrategyVersion.create(
        strategy_slug="ownership-fixture",
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="fixture",
    )
    holding = (
        None
        if staged
        else await model.OpenTrades.create(
            symbol=imported.symbol,
            lifecycle_mode="accumulation",
            accumulation_net_quantity=imported.quantity,
            accumulation_remaining_cost=imported.cost,
            accumulation_contributed_quote=imported.cost,
            accumulation_disposal_proceeds="0",
            accumulation_fees_json='{"totals":{},"pending_reports":1}',
            accumulation_basis_provenance="csv_declared_fees_unknown",
            execution_history_complete=False,
        )
    )
    activation = await model.AccumulationActivation.create(
        symbol=imported.symbol,
        account_scope="old-account",
        strategy_version=version,
        holding=holding,
        state="validating" if staged else state,
        explicitly_paused=staged or state != "enabled",
        observations_initialized=not staged,
        baseline_close_ms=None if staged else 1000,
        consumption_revision=0 if staged else 3,
        execution_guard_json=None if staged else '{"retained":"guard"}',
        revision=7,
    )
    entry = await model.AccumulationLifecycleOperation.create(
        activation=activation,
        operation_id="original-csv",
        action="activate",
        status="pending" if staged else "applied",
        request_json=json.dumps(
            {
                "source": "csv",
                "imported_inventory": imported.to_dict(),
                "account_scope": "old-account",
            }
        ),
        previous_state="validating",
        previous_paused=True,
        result_state=activation.state,
        result_revision=7,
        target_version=version,
    )
    wallet = SimpleNamespace(
        account_scope="new-account", free_base="2", observed_at_ms=NOW
    )
    config = {"exchange": "binance", "market": "spot", "dry_run": False}
    adapter = SimpleNamespace(
        config=lambda: dict(config),
        account_scope=AsyncMock(return_value="new-account"),
        account_inventory=AsyncMock(return_value=wallet),
        clock_ms=lambda: NOW,
    )
    payload = {
        "symbol": imported.symbol,
        "action": "declare_ownership",
        "operation_id": "declaration-1",
        "expected_revision": 7,
        "confirmation": imported.symbol,
        "note": "I own the recorded coins in this configured account",
    }
    return activation, holding, entry, adapter, wallet, config, payload


@pytest.mark.asyncio
async def test_csv_ownership_is_declared_without_inferred_identity_or_monetary_changes(
    ownership_db,
):
    activation, holding, _, adapter, _, _, payload = await declaration_fixture()
    original = await model.OpenTrades.get(id=holding.id).values()
    identity = (
        activation.generation,
        activation.strategy_version_id,
        activation.observation_epoch,
        activation.baseline_close_ms,
        activation.consumption_revision,
        activation.execution_guard_json,
    )
    result = await AccumulationOrderRepair(adapter).submit(payload)
    assert result.status == "applied" and result.state == "paused"
    await activation.refresh_from_db()
    await holding.refresh_from_db()
    current = await model.OpenTrades.get(id=holding.id).values()
    assert activation.account_scope == "new-account" and activation.explicitly_paused
    for key in (
        "accumulation_net_quantity",
        "accumulation_remaining_cost",
        "accumulation_contributed_quote",
        "accumulation_disposal_proceeds",
        "accumulation_fees_json",
    ):
        assert original[key] == current[key]
    assert not holding.execution_history_complete
    assert holding.accumulation_basis_provenance == "operator_declared_ownership"
    assert identity == (
        activation.generation,
        activation.strategy_version_id,
        activation.observation_epoch,
        activation.baseline_close_ms,
        activation.consumption_revision,
        activation.execution_guard_json,
    )
    assert await AccumulationOrderRepair(adapter).submit(payload) == result
    adapter.account_inventory.assert_awaited_once()
    assert await model.PlacementIntent.all().count() == 0
    assert await model.TradeExecutions.all().count() == 0


@pytest.mark.asyncio
async def test_changed_wallet_keeps_declaration_paused_and_retries_the_same_intent(
    ownership_db,
):
    activation, _, _, adapter, wallet, _, payload = await declaration_fixture()
    wallet.free_base = "0"
    result = await AccumulationOrderRepair(adapter).submit(payload)
    assert result.status == "quarantined"
    await activation.refresh_from_db()
    assert activation.account_scope == "old-account" and activation.explicitly_paused
    wallet.free_base = "2"
    result = await AccumulationOrderRepair(adapter).submit(payload)
    assert result.status == "applied"
    assert (
        await model.AccumulationLifecycleOperation.filter(
            action="declare_ownership"
        ).count()
        == 1
    )


@pytest.mark.asyncio
async def test_unadopted_entry_can_be_validated_again_only_by_a_new_explicit_request(
    ownership_db,
):
    activation, _, entry, adapter, _, _, payload = await declaration_fixture(
        staged=True
    )
    result = await AccumulationOrderRepair(adapter).submit(payload)
    assert result.status == "applied" and result.state == "paused"
    await entry.refresh_from_db()
    await activation.refresh_from_db()
    assert entry.status == "cancelled" and entry.reason == "ownership_scope_redeclared"
    assert not activation.observations_initialized and activation.holding_id is None
    command = StagedEntryCommand.from_dict(
        {
            "symbol": activation.symbol,
            "action": "retry_entry",
            "operation_id": "new-validation",
            "expected_revision": activation.revision,
            "previous_operation_id": entry.operation_id,
        },
        now_ms=NOW,
    )
    retried = await stage_entry_command(command, account_scope="new-account")
    assert retried.status == "pending"
    assert await model.OpenTrades.all().count() == 0


@pytest.mark.asyncio
async def test_declaring_closing_inventory_never_clears_dust_or_replays_a_sale(
    ownership_db,
):
    activation, holding, _, adapter, _, _, payload = await declaration_fixture(
        state="closing"
    )
    close = await model.AccumulationLifecycleOperation.create(
        activation=activation,
        operation_id="unplaced-close",
        action="close",
        status="quarantined",
        request_json="{}",
        previous_state="enabled",
        previous_paused=False,
        result_state="closing",
        result_revision=7,
    )
    result = await AccumulationOrderRepair(adapter).submit(payload)
    await activation.refresh_from_db()
    await close.refresh_from_db()
    assert result.state == "closing" and activation.explicitly_paused
    assert close.status == "cancelled" and close.reason == "restore_intent_retired"
    assert close.result_revision == activation.revision
    assert activation.holding_id == holding.id
    assert await model.PlacementIntent.all().count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["stale", "future", "scope", "config", "revision", "inventory"]
)
async def test_stale_or_changed_evidence_cannot_apply_an_ownership_declaration(
    ownership_db, change
):
    (
        activation,
        holding,
        _,
        adapter,
        wallet,
        config,
        payload,
    ) = await declaration_fixture()

    async def evidence(*args):
        if change == "stale":
            wallet.observed_at_ms = NOW - 10001
        elif change == "future":
            wallet.observed_at_ms = NOW + 1
        elif change == "scope":
            wallet.account_scope = "wrong-account"
        elif change == "config":
            config["exchange"] = "other"
        elif change == "revision":
            await model.AccumulationActivation.filter(id=activation.id).update(
                revision=100
            )
        elif change == "inventory":
            await model.OpenTrades.filter(id=holding.id).update(
                accumulation_net_quantity="0.5"
            )
        return wallet

    adapter.account_inventory.side_effect = evidence
    if change == "scope":
        assert (
            await AccumulationOrderRepair(adapter).submit(payload)
        ).status == "quarantined"
    else:
        with pytest.raises(AccumulationConflictError):
            await AccumulationOrderRepair(adapter).submit(payload)
    await activation.refresh_from_db()
    assert activation.account_scope == "old-account"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"confirmation": "BTC"},
        {"note": ""},
        {"note": "reason\nsecret"},
        {"expected_revision": True},
        {"account_scope": "client supplied"},
    ],
)
async def test_confirmation_and_canonical_identity_are_required_before_wallet_reads(
    ownership_db, changes
):
    _, _, _, adapter, _, _, payload = await declaration_fixture()
    with pytest.raises(AccumulationStateError):
        await AccumulationOrderRepair(adapter).submit({**payload, **changes})
    adapter.account_inventory.assert_not_awaited()


@pytest.mark.asyncio
async def test_declaration_scope_commit_rolls_back_and_competing_clients_cannot_double_apply(
    ownership_db, monkeypatch
):
    activation, holding, _, adapter, _, _, payload = await declaration_fixture()
    save = model.AccumulationActivation.save

    async def failing(row, *args, **kwargs):
        if row.account_scope == "new-account":
            raise RuntimeError("scope write failed")
        await save(row, *args, **kwargs)

    monkeypatch.setattr(model.AccumulationActivation, "save", failing)
    with pytest.raises(RuntimeError, match="scope write failed"):
        await AccumulationOrderRepair(adapter).submit(payload)
    await activation.refresh_from_db()
    await holding.refresh_from_db()
    assert activation.account_scope == "old-account"
    assert holding.accumulation_basis_provenance == "csv_declared_fees_unknown"
    monkeypatch.setattr(model.AccumulationActivation, "save", save)
    results = await asyncio.gather(
        *[AccumulationOrderRepair(adapter).submit(payload) for _ in range(8)]
    )
    assert all(result.status == "applied" for result in results)
    assert len({result.revision for result in results}) == 1


@pytest.mark.asyncio
async def test_abandoned_unadopted_entry_can_be_explicitly_validated_again(
    ownership_db,
):
    activation, _, entry, _, _, _, _ = await declaration_fixture(staged=True)
    abandoned = await stage_entry_command(
        StagedEntryCommand.from_dict(
            {
                "symbol": activation.symbol,
                "action": "abandon_entry",
                "operation_id": "abandon-explicit",
                "expected_revision": 7,
                "previous_operation_id": entry.operation_id,
            },
            now_ms=NOW,
        ),
        account_scope="old-account",
    )
    assert abandoned.state == "stopped"
    retried = await stage_entry_command(
        StagedEntryCommand.from_dict(
            {
                "symbol": activation.symbol,
                "action": "retry_entry",
                "operation_id": "restart-explicit",
                "expected_revision": abandoned.revision,
                "previous_operation_id": abandoned.operation_id,
            },
            now_ms=NOW,
        ),
        account_scope="old-account",
    )
    assert retried.status == "pending" and retried.state == "validating"
    await activation.refresh_from_db()
    assert activation.holding_id is None and activation.explicitly_paused
    assert (
        not activation.observations_initialized and activation.consumption_revision == 0
    )
    assert await model.PlacementIntent.all().count() == 0


@pytest.mark.asyncio
async def test_corrupt_unadopted_declaration_can_be_abandoned_without_adoption(
    ownership_db,
):
    activation, _, entry, _, _, _, _ = await declaration_fixture(staged=True)
    entry.request_json = "[]"
    await entry.save()
    result = await stage_entry_command(
        StagedEntryCommand.from_dict(
            {
                "symbol": activation.symbol,
                "action": "abandon_entry",
                "operation_id": "abandon-corrupt",
                "expected_revision": 7,
                "previous_operation_id": entry.operation_id,
            },
            now_ms=NOW,
        ),
        account_scope="old-account",
    )
    assert result.state == "stopped" and result.status == "applied"
    assert await model.OpenTrades.all().count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("deleted", [False, True])
async def test_missing_csv_inventory_is_restored_only_from_the_original_declaration(
    ownership_db, monkeypatch, deleted
):
    activation, holding, _, adapter, wallet, _, _ = await declaration_fixture(
        state="paused"
    )
    monkeypatch.setattr(
        "service.accumulation_inventory_restore.lifecycle_mutation_coordinator",
        LifecycleMutationCoordinator(TradingMaintenanceBarrier()),
    )
    original = await model.OpenTrades.get(id=holding.id).values()
    activation.holding_id = None
    await activation.save()
    if deleted:
        await holding.delete()
    wallet.account_scope = "old-account"
    adapter.account_scope.return_value = "old-account"
    payload = {
        "symbol": activation.symbol,
        "action": "restore_inventory",
        "operation_id": "restore-inventory-1",
        "expected_revision": 7,
    }
    result = await AccumulationOrderRepair(adapter).submit(payload)
    assert result.state == "paused" and result.status == "applied"
    await activation.refresh_from_db()
    restored = await model.OpenTrades.get(id=activation.holding_id)
    current = await model.OpenTrades.get(id=restored.id).values()
    for key in (
        "accumulation_net_quantity",
        "accumulation_remaining_cost",
        "accumulation_contributed_quote",
        "accumulation_disposal_proceeds",
        "accumulation_basis_provenance",
    ):
        assert current[key] == original[key]
    assert not restored.execution_history_complete
    assert (
        activation.consumption_revision == 3
        and activation.execution_guard_json == '{"retained":"guard"}'
    )
    assert await AccumulationOrderRepair(adapter).submit(payload) == result
    adapter.account_inventory.assert_awaited_once()
    assert await model.PlacementIntent.all().count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "wallet",
        "foreign_holding",
        "changed_quantity",
        "unpaused",
        "wrong_scope",
        "missing_declaration",
    ],
)
async def test_inventory_restore_rejects_missing_or_conflicting_evidence(
    ownership_db, monkeypatch, fault
):
    activation, holding, entry, adapter, wallet, _, _ = await declaration_fixture(
        state="paused"
    )
    monkeypatch.setattr(
        "service.accumulation_inventory_restore.lifecycle_mutation_coordinator",
        LifecycleMutationCoordinator(TradingMaintenanceBarrier()),
    )
    activation.holding_id = None
    await activation.save()
    adapter.account_scope.return_value = "old-account"
    wallet.account_scope = "old-account"
    if fault == "wallet":
        wallet.free_base = "0"
    elif fault == "foreign_holding":
        holding.lifecycle_mode = "classic_dca"
        await holding.save()
    elif fault == "changed_quantity":
        holding.accumulation_net_quantity = "1.5"
        await holding.save()
    elif fault == "unpaused":
        activation.explicitly_paused = False
        await activation.save()
    elif fault == "wrong_scope":
        adapter.account_scope.return_value = "new-account"
    elif fault == "missing_declaration":
        entry.request_json = "{}"
        await entry.save()
    with pytest.raises(AccumulationConflictError):
        await AccumulationOrderRepair(adapter).submit(
            {
                "symbol": activation.symbol,
                "action": "restore_inventory",
                "operation_id": "restore-rejected",
                "expected_revision": 7,
            }
        )
    await activation.refresh_from_db()
    assert activation.holding_id is None and activation.revision == 7


@pytest.mark.asyncio
async def test_abandoned_entry_can_use_a_new_reviewed_compatible_pin(ownership_db):
    from service.accumulation_strategy import build_accumulation_strategy_document

    activation, _, entry, _, _, _, _ = await declaration_fixture(staged=True)
    abandoned = await stage_entry_command(
        StagedEntryCommand.from_dict(
            {
                "symbol": activation.symbol,
                "action": "abandon_entry",
                "operation_id": "abandon-pin",
                "expected_revision": 7,
                "previous_operation_id": entry.operation_id,
            },
            now_ms=NOW,
        ),
        account_scope="old-account",
    )
    version = await model.StrategyVersion.create(
        strategy_slug="replacement-pin",
        version=1,
        ir_json=json.dumps(build_accumulation_strategy_document()),
        validation_json="{}",
        explanation="fixture",
    )
    command = StagedEntryCommand.from_dict(
        {
            "symbol": activation.symbol,
            "action": "retry_entry",
            "operation_id": "restart-new-pin",
            "expected_revision": abandoned.revision,
            "previous_operation_id": abandoned.operation_id,
            "target_version_id": version.id,
        },
        now_ms=NOW,
    )
    result = await stage_entry_command(command, account_scope="old-account")
    assert result.status == "pending"
    await activation.refresh_from_db()
    assert activation.strategy_version_id == version.id
    assert (
        await model.AccumulationLifecycleOperation.get(
            operation_id=command.operation_id
        )
    ).target_version_id == version.id
    assert await stage_entry_command(command, account_scope="old-account") == result
    assert not await model.OpenTrades.exists()
