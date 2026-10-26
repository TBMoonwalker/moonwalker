"""SQLite regression coverage for explicit inventory declarations, never fills."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import model
import pytest
import pytest_asyncio
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_repair import AccumulationOrderRepair
from service.accumulation_state import AccumulationConflictError
from service.accumulation_status import get_accumulation_status
from service.lifecycle_mutation import LifecycleMutationCoordinator
from service.trading_maintenance import TradingMaintenanceBarrier
from tortoise import Tortoise


@pytest_asyncio.fixture
async def adjustment(tmp_path, monkeypatch):
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'adjustment.sqlite'}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()
    monkeypatch.setattr(
        "service.accumulation_adjustment.lifecycle_mutation_coordinator",
        LifecycleMutationCoordinator(TradingMaintenanceBarrier()),
    )
    version = await model.StrategyVersion.create(
        strategy_slug="adjustment",
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="fixture",
    )
    holding = await model.OpenTrades.create(
        symbol="BTC/USDC",
        lifecycle_mode="accumulation",
        amount=2,
        cost=20,
        accumulation_net_quantity="2",
        accumulation_remaining_cost="20",
        accumulation_contributed_quote="30",
        accumulation_disposal_proceeds="12",
        accumulation_basis_provenance="csv_declared",
        execution_history_complete=False,
        accumulation_fees_json='{"totals":{"USDC":"1"},"pending_reports":0}',
    )
    activation = await model.AccumulationActivation.create(
        symbol=holding.symbol,
        account_scope="account",
        strategy_version=version,
        holding=holding,
        state="paused",
        explicitly_paused=True,
        revision=7,
        observations_initialized=True,
        baseline_close_ms=1000,
        consumption_revision=3,
        execution_guard_json='{"retained":"guard"}',
    )
    config = {"exchange": "binance", "dry_run": False}
    wallet = SimpleNamespace(
        account_scope="account", free_base="4", observed_at_ms=1000
    )
    adapter = SimpleNamespace(
        config=lambda: dict(config),
        account_scope=AsyncMock(return_value="account"),
        clock_ms=lambda: 1000,
        account_inventory=AsyncMock(return_value=wallet),
    )
    payload = dict(
        symbol=holding.symbol,
        action="adjust_inventory",
        operation_id="adjust-1",
        expected_revision=7,
        direction="add",
        quantity="0.000000000000000001",
        acquisition_cost="0.000000000000000009",
        note="Correct net CSV quantity",
    )
    yield activation, holding, adapter, payload, config, wallet
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_exact_adjustment_is_audited_idempotent_and_does_not_change_purchase_guards(
    adjustment,
):
    activation, holding, adapter, payload, _, _ = adjustment
    before_activation = await model.AccumulationActivation.get(
        id=activation.id
    ).values()
    result = await AccumulationOrderRepair(adapter).submit(payload)
    assert (
        result.status == "applied" and result.state == "paused" and result.revision == 8
    )
    await holding.refresh_from_db()
    assert holding.accumulation_net_quantity == "2.000000000000000001"
    assert holding.accumulation_remaining_cost == "20.000000000000000009"
    assert holding.accumulation_contributed_quote == "30.000000000000000009"
    assert holding.accumulation_disposal_proceeds == "12"
    assert json.loads(holding.accumulation_fees_json)["totals"] == {"USDC": "1"}
    assert holding.accumulation_basis_provenance == "operator_adjusted"
    assert not holding.execution_history_complete
    current = await model.AccumulationActivation.get(id=activation.id).values()
    for key in (
        "generation",
        "holding_id",
        "strategy_version_id",
        "observation_epoch",
        "baseline_close_ms",
        "consumption_revision",
        "execution_guard_json",
        "state",
        "explicitly_paused",
    ):
        assert current[key] == before_activation[key]
    assert await model.AccumulationFillCheckpoint.all().count() == 0
    assert await model.PlacementIntent.all().count() == 0
    again = await AccumulationOrderRepair(adapter).submit(payload)
    assert again == result and adapter.account_inventory.await_count == 1
    status = await get_accumulation_status(holding.symbol, wait_reasons={})
    audit = status["operations"][0]["adjustment"]
    assert (
        audit["before_quantity"] == "2"
        and audit["after_quantity"] == holding.accumulation_net_quantity
    )
    assert audit["note"] == payload["note"]
    assert "account_scope" not in json.dumps(status)
    with pytest.raises(AccumulationConflictError, match="Operation ID"):
        await AccumulationOrderRepair(adapter).submit(
            {**payload, "note": "Different request"}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", [False, True])
async def test_partial_removal_allocates_basis_without_inventing_sale_proceeds(
    adjustment, unknown
):
    _, holding, adapter, payload, _, _ = adjustment
    if unknown:
        holding.accumulation_remaining_cost = None
        holding.accumulation_contributed_quote = None
        await holding.save()
    await AccumulationOrderRepair(adapter).submit(
        {**payload, "direction": "remove", "quantity": "0.5", "acquisition_cost": None}
    )
    await holding.refresh_from_db()
    assert holding.accumulation_net_quantity == "1.5"
    assert (
        holding.accumulation_remaining_cost is None
        if unknown
        else holding.accumulation_remaining_cost
        == "15.000000000000000000000000000000000000"
    )
    assert (
        holding.accumulation_contributed_quote is None
        if unknown
        else holding.accumulation_contributed_quote == "30"
    )
    assert holding.accumulation_disposal_proceeds == "12"


@pytest.mark.asyncio
async def test_unknown_added_cost_never_becomes_zero_basis(adjustment):
    _, holding, adapter, payload, _, _ = adjustment
    await AccumulationOrderRepair(adapter).submit({**payload, "acquisition_cost": None})
    await holding.refresh_from_db()
    assert holding.accumulation_remaining_cost is None
    assert holding.accumulation_contributed_quote is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "enabled",
        "closing",
        "stopped",
        "unlinked",
        "account",
        "revision",
        "uninitialized",
        "pending",
        "fees",
        "shared_base",
    ],
)
async def test_unsafe_ownership_or_execution_blocks_before_wallet_read(
    adjustment, change
):
    activation, holding, adapter, payload, _, _ = adjustment
    if change in {"enabled", "closing", "stopped"}:
        activation.state = change
    elif change == "unlinked":
        activation.holding_id = None
    elif change == "account":
        activation.account_scope = "different"
    elif change == "revision":
        activation.revision += 1
    elif change == "uninitialized":
        activation.observations_initialized = False
    elif change == "pending":
        await model.AccumulationLifecycleOperation.create(
            activation=activation,
            operation_id="unresolved",
            action="close",
            request_json="{}",
            status="quarantined",
            previous_state="paused",
            previous_paused=True,
            result_state="paused",
            result_revision=7,
        )
    elif change == "fees":
        holding.accumulation_fees_json = '{"totals":{},"pending_reports":1}'
        await holding.save()
    elif change == "shared_base":
        await model.OpenTrades.create(symbol="BTC/EUR")
    await activation.save()
    with pytest.raises(AccumulationConflictError):
        await AccumulationOrderRepair(adapter).submit(payload)
    adapter.account_inventory.assert_not_awaited()
    assert (
        await model.AccumulationLifecycleOperation.filter(
            action="adjust_inventory"
        ).count()
        == 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["shortfall", "stale", "scope", "config", "ledger", "revision"]
)
async def test_wallet_and_commit_races_do_not_apply_corrections(adjustment, change):
    activation, holding, adapter, payload, config, wallet = adjustment

    async def evidence(*args):
        if change == "shortfall":
            wallet.free_base = "2"
        elif change == "stale":
            wallet.observed_at_ms = -10000
        elif change == "scope":
            wallet.account_scope = "other"
        elif change == "config":
            config["exchange"] = "other"
        elif change == "ledger":
            holding.accumulation_disposal_proceeds = "13"
            await holding.save()
        elif change == "revision":
            activation.revision += 1
            await activation.save()
        return wallet

    adapter.account_inventory.side_effect = evidence
    with pytest.raises(AccumulationConflictError):
        await AccumulationOrderRepair(adapter).submit(payload)
    await holding.refresh_from_db()
    assert holding.accumulation_net_quantity == "2"
    assert (
        await model.AccumulationLifecycleOperation.filter(
            action="adjust_inventory"
        ).count()
        == 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "values",
    [
        {"direction": "remove", "quantity": "2", "acquisition_cost": None},
        {"direction": "remove", "acquisition_cost": "1"},
        {"quantity": 0.1},
        {"quantity": "0"},
        {"quantity": "NaN"},
        {"acquisition_cost": "-1"},
        {"note": ""},
        {"note": "reason\nsecret"},
        {"expected_revision": True},
        {"account_scope": "untrusted"},
    ],
)
async def test_invalid_request_cannot_write_off_inventory_or_send_network_reads(
    adjustment, values
):
    _, _, adapter, payload, _, _ = adjustment
    with pytest.raises(AccumulationStateError):
        await AccumulationOrderRepair(adapter).submit({**payload, **values})
    adapter.account_inventory.assert_not_awaited()


@pytest.mark.asyncio
async def test_competing_clients_apply_one_revision_and_atomic_rollback(
    adjustment, monkeypatch
):
    _, holding, adapter, payload, _, _ = adjustment
    original_save = model.AccumulationActivation.save

    async def fail(*args, **kwargs):
        raise RuntimeError("disk failure")

    monkeypatch.setattr(model.AccumulationActivation, "save", fail)
    with pytest.raises(RuntimeError, match="disk failure"):
        await AccumulationOrderRepair(adapter).submit(payload)
    await holding.refresh_from_db()
    assert holding.accumulation_net_quantity == "2"
    assert (
        await model.AccumulationLifecycleOperation.filter(
            action="adjust_inventory"
        ).count()
        == 0
    )
    monkeypatch.setattr(model.AccumulationActivation, "save", original_save)
    results = await asyncio.gather(
        *[
            AccumulationOrderRepair(adapter).submit(
                {**payload, "operation_id": f"race-{index}"}
            )
            for index in range(8)
        ],
        return_exceptions=True,
    )
    assert sum(not isinstance(item, BaseException) for item in results) == 1
    assert (
        await model.AccumulationLifecycleOperation.filter(
            action="adjust_inventory"
        ).count()
        == 1
    )
