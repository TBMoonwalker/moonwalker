"""Accumulation restore preserves ownership and never replays external effects."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import model
import pytest
import pytest_asyncio
from service.accumulation_recovery import AccumulationPlacementRecovery
from service.accumulation_strategy import build_accumulation_strategy_document
from service.backup_restore import BackupService
from tortoise import Tortoise


@pytest_asyncio.fixture
async def backup_db(tmp_path, monkeypatch):
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'backup.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    config = SimpleNamespace(reload=AsyncMock(), snapshot=lambda: {})
    monkeypatch.setattr(
        "service.backup_restore.Config.instance", AsyncMock(return_value=config)
    )
    monkeypatch.setattr(
        BackupService, "_refresh_required_history", AsyncMock(return_value=([], []))
    )
    yield
    await Tortoise.close_connections()


async def _seed(state="closing", placement_state="accepted"):
    await model.AppConfig.create(key="timezone", value="UTC", value_type="str")
    await model.StrategyDefinition.create(
        slug="acc", name="Accumulate", active_version=2
    )
    version = await model.StrategyVersion.create(
        id=51,
        strategy_slug="acc",
        version=1,
        ir_json='{"pinned":true}',
        validation_json="{}",
        explanation="Pinned strategy",
    )
    await model.StrategyVersion.create(
        id=52,
        strategy_slug="acc",
        version=2,
        ir_json='{"newer":true}',
        validation_json="{}",
        explanation="Not the pin",
    )
    holding = None
    if state != "stopped":
        holding = await model.OpenTrades.create(
            id=42,
            symbol="BTC/USDC",
            lifecycle_mode="accumulation",
            accumulation_net_quantity="0.000000000000000123",
            accumulation_remaining_cost=None,
            accumulation_contributed_quote="3.000000000000000007",
            accumulation_disposal_proceeds="1.000000000000000003",
            accumulation_fees_json='{"BTC":"0.000000000000000001"}',
            accumulation_basis_provenance="imported_unknown",
        )
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC",
        account_scope="source-account",
        state=state,
        explicitly_paused=False,
        strategy_version=version,
        holding=holding,
        baseline_close_ms=1000,
        revision=7,
        observation_epoch=4,
        consumption_revision=3,
        execution_guard_json='{"anchor":"123.00000000000001"}',
    )
    await model.AccumulationStrategyState.create(
        activation=activation,
        strategy_version=version,
        observation_epoch=4,
        value_json='{"history":[1,2,3]}',
        last_processed_close_ms=1000,
    )
    opportunity = await model.AccumulationOpportunity.create(
        activation=activation,
        generation=activation.generation,
        strategy_version=version,
        observation_epoch=4,
        signal_close_ms=1000,
        expires_at_ms=2000,
        signal_price="123",
        signal_atr="3",
        status="consumed",
        consumption_revision=3,
        unresolved_slot=activation.id if placement_state == "accepted" else None,
    )
    placement = await model.PlacementIntent.create(
        id=62,
        operation_id="original-buy",
        client_order_id="original-client",
        exchange_order_id="original-exchange",
        exchange_name="binance",
        symbol="BTC/USDC",
        action="buy",
        side="buy",
        order_type="limit",
        state=placement_state,
        requested_quote=3,
        reserved_quote=3,
        request_json=json.dumps({"activation_id": str(activation.id)}),
        result_json='{"filled":"0.000000000000000123"}',
    )
    await model.AccumulationAttempt.create(opportunity=opportunity, placement=placement)
    await model.AccumulationFillCheckpoint.create(
        activation=activation,
        placement=placement,
        filled="0.000000000000000123",
        quote_cost="3.000000000000000007",
        evidence_json=placement.result_json,
    )
    await model.AccumulationLifecycleOperation.create(
        operation_id="close-command",
        activation=activation,
        action="close",
        request_json='{"action":"close"}',
        previous_state="enabled",
        previous_paused=False,
        result_state=state,
        result_revision=7,
        status="completed" if state == "stopped" else "pending",
    )
    return activation


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["enabled", "paused", "closing", "stopped"])
async def test_full_restore_preserves_graph_and_quarantines_work(backup_db, state):
    activation = await _seed(state)
    service = BackupService()
    payload = json.loads(json.dumps(await service.export_backup(True)))
    assert payload["schema_version"] == 3
    assert [v["id"] for v in payload["accumulation_strategies"]["versions"]] == [51]
    for _ in range(2):  # A restored backup remains portable without losing its graph.
        await service.restore_backup(payload, restore_trade_data=True)
        restored = await model.AccumulationActivation.get(id=activation.id)
        assert restored.generation == activation.generation
        assert restored.state == ("paused" if state == "enabled" else state)
        assert restored.explicitly_paused
        assert restored.execution_guard_json == activation.execution_guard_json
        assert restored.consumption_revision == 3
        assert restored.observation_epoch == 4
        assert restored.strategy_version_id == 51
        assert (await model.StrategyDefinition.get(slug="acc")).active_version == 2
        if state != "stopped":
            holding = await model.OpenTrades.get(id=restored.holding_id)
            assert holding.id == 42
            assert holding.accumulation_net_quantity == "0.000000000000000123"
            assert holding.accumulation_remaining_cost is None
            assert holding.automation_paused
        else:
            assert restored.holding_id is None
        attempt = await model.AccumulationAttempt.get()
        placement = await attempt.placement
        checkpoint = await model.AccumulationFillCheckpoint.get(
            placement_id=placement.id
        )
        assert placement.state == "restored_quarantined"
        assert placement.operation_id == "original-buy"
        assert placement.client_order_id == "original-client"
        assert placement.exchange_order_id == "original-exchange"
        assert checkpoint.quote_cost == "3.000000000000000007"
        command = await model.AccumulationLifecycleOperation.get()
        assert command.status == ("completed" if state == "stopped" else "quarantined")
        assert await model.AccumulationStrategyState.all().count() == 1
        payload = json.loads(json.dumps(await service.export_backup(True)))


@pytest.mark.asyncio
async def test_restore_into_empty_catalog_keeps_exact_pin_without_publishing(backup_db):
    activation = await _seed("stopped", "completed")
    service = BackupService()
    payload = await service.export_backup(True)
    # Remove only the local catalog binding after clearing its dependent state.
    from service.accumulation_backup import ACCUMULATION_TABLE_MODELS

    for table in reversed(ACCUMULATION_TABLE_MODELS.values()):
        await table.all().delete()
    await model.StrategyVersion.all().delete()
    await model.StrategyDefinition.all().delete()
    await service.restore_backup(payload, restore_trade_data=True)
    assert (
        await model.AccumulationActivation.get(id=activation.id)
    ).strategy_version_id == 51
    assert (await model.StrategyVersion.get(id=51)).ir_json == '{"pinned":true}'
    assert (await model.StrategyDefinition.get(slug="acc")).active_version is None
    assert (await model.PlacementIntent.get(id=62)).state == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "damage", ["holding", "strategy", "attempt", "checkpoint", "duplicate", "orphan"]
)
async def test_broken_graph_rejected_without_changing_live_rows(backup_db, damage):
    activation = await _seed()
    service = BackupService()
    payload = await service.export_backup(True)
    tables = payload["trade_data"]
    if damage == "holding":
        tables["open_trades"] = []
    elif damage == "strategy":
        payload["accumulation_strategies"]["versions"] = []
    elif damage == "attempt":
        tables["accumulation_attempts"][0]["opportunity_id"] = str(uuid4())
    elif damage == "checkpoint":
        tables["accumulation_fill_checkpoints"][0]["placement_id"] = 999
    elif damage == "duplicate":
        tables["accumulation_activations"].append(
            copy.deepcopy(tables["accumulation_activations"][0])
        )
    else:
        tables["accumulation_activations"] = []
    with pytest.raises(ValueError):
        await service.restore_backup(payload, restore_trade_data=True)
    assert (await model.AccumulationActivation.get(id=activation.id)).revision == 7
    assert (await model.PlacementIntent.get(id=62)).state == "accepted"
    assert not await model.AppConfig.filter(key="dry_run").exists()


@pytest.mark.asyncio
async def test_strategy_collision_rolls_back_all_restore_changes(backup_db):
    activation = await _seed()
    service = BackupService()
    payload = await service.export_backup(True)
    payload["accumulation_strategies"]["versions"][0]["ir_json"] = '{"changed":true}'
    with pytest.raises(ValueError, match="conflicts"):
        await service.restore_backup(payload, restore_trade_data=True)
    assert (await model.AccumulationActivation.get(id=activation.id)).revision == 7
    assert (await model.StrategyVersion.get(id=51)).ir_json == '{"pinned":true}'
    assert not await model.AppConfig.filter(key="dry_run").exists()


@pytest.mark.asyncio
async def test_config_only_restore_keeps_accumulation_identity(backup_db):
    activation = await _seed()
    service = BackupService()
    payload = await service.export_backup(False)
    await service.restore_backup(payload, restore_trade_data=False)
    assert (await model.AccumulationActivation.get(id=activation.id)).revision == 7
    assert (await model.PlacementIntent.get(id=62)).state == "accepted"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["quarantined", "restored_quarantined"])
async def test_recovery_cannot_lookup_or_account_quarantined_identity(state):
    exchange = SimpleNamespace(lookup_spot_order=AsyncMock())
    scope = AsyncMock()
    recovery = AccumulationPlacementRecovery(exchange, scope)
    assert await recovery.reconcile(SimpleNamespace(state=state), {}) == state
    scope.assert_not_awaited()
    exchange.lookup_spot_order.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["table", "guard", "consumption"])
async def test_incomplete_snapshot_cannot_default_to_fresh_state(backup_db, missing):
    activation = await _seed()
    service = BackupService()
    payload = await service.export_backup(True)
    if missing == "table":
        del payload["trade_data"]["accumulation_strategy_states"]
    else:
        field = "execution_guard_json" if missing == "guard" else "consumption_revision"
        del payload["trade_data"]["accumulation_activations"][0][field]
    with pytest.raises(ValueError):
        await service.restore_backup(payload, restore_trade_data=True)
    assert (await model.AccumulationActivation.get(id=activation.id)).revision == 7


@pytest.mark.asyncio
async def test_close_retry_chain_and_target_pin_survive_restore(backup_db):
    activation = await _seed("closing", "completed")
    prior = await model.PlacementIntent.create(
        operation_id="prior-sale",
        symbol=activation.symbol,
        state="completed",
        exchange_name="binance",
        action="sell",
        side="sell",
        order_type="market",
    )
    close = await model.AccumulationLifecycleOperation.get(operation_id="close-command")
    close.status = "continued"
    close.placement = prior
    await close.save()
    retry = await model.PlacementIntent.create(
        operation_id="retry-sale",
        source_operation_id=prior.operation_id,
        symbol=activation.symbol,
        state="indeterminate",
        exchange_name="binance",
        action="sell",
        side="sell",
        order_type="market",
        client_order_id="retry-client",
    )
    await model.AccumulationLifecycleOperation.create(
        operation_id="retry-command",
        activation=activation,
        action="retry_close",
        request_json='{"previous_operation_id":"close-command"}',
        previous_state="closing",
        previous_paused=True,
        result_state="closing",
        result_revision=7,
        placement=retry,
        target_version_id=52,
    )
    service = BackupService()
    payload = await service.export_backup(True)
    assert {v["id"] for v in payload["accumulation_strategies"]["versions"]} == {51, 52}
    await service.restore_backup(payload, restore_trade_data=True)
    restored = await model.AccumulationLifecycleOperation.get(
        operation_id="retry-command"
    )
    assert restored.status == "quarantined"
    assert restored.placement_id == retry.id
    assert restored.target_version_id == 52
    assert restored.request_json == '{"previous_operation_id":"close-command"}'
    placement = await restored.placement
    assert placement.source_operation_id == prior.operation_id
    assert placement.client_order_id == "retry-client"
    assert placement.state == "restored_quarantined"
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id="close-command")
    ).status == "continued"


@pytest.mark.asyncio
async def test_full_backup_carries_initial_pin_without_an_activation(backup_db):
    await model.StrategyDefinition.create(
        slug="initial-pin", name="Initial accumulation", active_version=1
    )
    version = await model.StrategyVersion.create(
        id=73,
        strategy_slug="initial-pin",
        version=1,
        ir_json=json.dumps(build_accumulation_strategy_document()),
        validation_json="{}",
        explanation="test",
    )
    await model.AppConfig.create(
        key="trade_mode", value="accumulation", value_type="str"
    )
    await model.AppConfig.create(
        key="accumulation_strategy_version_id", value=str(version.id), value_type="int"
    )
    service = BackupService()
    full = await service.export_backup(True)
    assert [row["id"] for row in full["accumulation_strategies"]["versions"]] == [73]
    config_only = await service.export_backup(False)
    await service.restore_backup(config_only, restore_trade_data=False)
    assert (
        await model.AppConfig.get_or_none(key="accumulation_strategy_version_id")
        is None
    )
    assert (await model.AppConfig.get(key="trade_mode")).value == "accumulation"
    await model.StrategyVersion.filter(id=73).delete()
    await model.StrategyDefinition.filter(slug="initial-pin").delete()
    await service.restore_backup(full, restore_trade_data=True)
    assert (
        await model.AppConfig.get(key="accumulation_strategy_version_id")
    ).value == "73"
    restored = await model.StrategyVersion.get(id=73)
    assert restored.ir_json == version.ir_json
    assert not await model.AccumulationActivation.all().exists()


@pytest.mark.asyncio
async def test_missing_initial_strategy_dependency_rejects_restore_before_writes(
    backup_db,
):
    await model.StrategyDefinition.create(
        slug="initial-pin", name="Initial accumulation", active_version=1
    )
    version = await model.StrategyVersion.create(
        strategy_slug="initial-pin",
        version=1,
        ir_json=json.dumps(build_accumulation_strategy_document()),
        validation_json="{}",
        explanation="test",
    )
    await model.AppConfig.create(
        key="accumulation_strategy_version_id", value=str(version.id), value_type="int"
    )
    service = BackupService()
    payload = await service.export_backup(True)
    payload["accumulation_strategies"]["versions"] = []
    with pytest.raises(ValueError, match="missing or unrelated strategy pins"):
        await service.restore_backup(payload, restore_trade_data=True)
    assert (
        await model.AppConfig.get(key="accumulation_strategy_version_id")
    ).value == str(version.id)
    await model.StrategyVersion.filter(id=version.id).delete()
    with pytest.raises(ValueError, match="missing a selected strategy"):
        await service.export_backup(True)


@pytest.mark.asyncio
async def test_restore_preserves_audit_update_times_used_for_latest_inventory_order(
    backup_db,
):
    from datetime import datetime, timezone

    await _seed(state="paused")
    original = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    await model.AccumulationFillCheckpoint.all().update(updated_at=original)
    await model.AccumulationLifecycleOperation.all().update(updated_at=original)
    service = BackupService()
    payload = json.loads(json.dumps(await service.export_backup(True)))
    await service.restore_backup(payload, restore_trade_data=True)
    assert (await model.AccumulationFillCheckpoint.get()).updated_at == original
    assert (await model.AccumulationLifecycleOperation.get()).updated_at == original
