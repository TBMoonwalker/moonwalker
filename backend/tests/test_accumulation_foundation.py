"""Real-database regression coverage for accumulation storage boundaries."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import model
import pytest
import pytest_asyncio
from service.accumulation.contracts import (
    AccumulationIdentity,
    AccumulationStateError,
    canonical_decimal,
    decode_observations,
    encode_observations,
)
from service.accumulation.state import (
    AccumulationConflictError,
    load_accumulation_context,
    save_accumulation_observations,
)
from service.lifecycle_snapshot import LifecycleSnapshotIdentity, snapshots_match
from service.spot_campaign_types import parse_lifecycle_mode
from service.strategy_persistence import delete_custom_strategy
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError, OperationalError


@pytest_asyncio.fixture
async def accumulation_db(tmp_path):
    db_url = f"sqlite://{tmp_path / 'accumulation.sqlite'}"
    await Tortoise.init(db_url=db_url, modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    yield db_url
    await Tortoise.close_connections()


async def _activation(**overrides):
    definition = await model.StrategyDefinition.create(
        slug="custom_accumulate", name="Accumulation fixture", active_version=1
    )
    version = await model.StrategyVersion.create(
        strategy_slug=definition.slug,
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="Storage fixture only",
    )
    return await model.AccumulationActivation.create(
        symbol="BTC/USDC",
        account_scope="test-account",
        strategy_version=version,
        baseline_close_ms=1000,
        **overrides,
    )


async def _context(activation):
    return await load_accumulation_context(str(activation.id), activation.account_scope)


@pytest.mark.asyncio
async def test_stopped_activation_survives_holding_delete_and_restart(accumulation_db):
    holding = await model.OpenTrades.create(symbol="BTC/USDC")
    activation = await _activation(state="stopped", holding=holding)
    generation = activation.generation
    await holding.delete()
    await Tortoise.close_connections()
    await Tortoise.init(db_url=accumulation_db, modules={"models": ["model"]})
    restored = await model.AccumulationActivation.get(id=activation.id)
    assert restored.state == "stopped"
    assert restored.holding_id is None
    assert restored.generation == generation
    assert restored.explicitly_paused
    with pytest.raises(IntegrityError):
        await model.AccumulationActivation.create(
            symbol="BTC/USDC", account_scope="different-account"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["enabled", "paused", "stopped"])
async def test_pinned_strategy_cannot_be_deleted_or_auto_updated(
    accumulation_db, state
):
    activation = await _activation(state=state)
    await model.StrategyVersion.create(
        strategy_slug="custom_accumulate",
        version=2,
        ir_json="{}",
        validation_json="{}",
        explanation="New version",
    )
    await model.StrategyDefinition.filter(slug="custom_accumulate").update(
        active_version=2
    )
    assert (await _context(activation)).identity.strategy_version == 1
    with pytest.raises(PermissionError, match="referenced by accumulation"):
        await delete_custom_strategy("custom_accumulate")
    with pytest.raises(IntegrityError):
        await model.StrategyVersion.filter(id=activation.strategy_version_id).delete()
    assert await model.StrategyDefinition.filter(slug="custom_accumulate").exists()
    # Explicitly unbinding an unused activation releases the reference.
    activation.strategy_version_id = None
    await activation.save()
    await delete_custom_strategy("custom_accumulate")


@pytest.mark.asyncio
async def test_observations_distinguish_first_use_corruption_and_missing_state(
    accumulation_db,
):
    activation = await _activation(
        consumption_revision=7, execution_guard_json='{"anchor":"97"}'
    )
    initial = await _context(activation)
    assert initial.observations is None
    updated = await save_accumulation_observations(
        initial.identity, {"recovery_high": "100"}, 2000
    )
    assert updated.revision == 1
    assert updated.consumption_revision == 7
    await activation.refresh_from_db()
    assert activation.execution_guard_json == '{"anchor":"97"}'
    assert (await _context(activation)).observations == {"recovery_high": "100"}
    await model.AccumulationStrategyState.all().update(value_json="broken JSON")
    with pytest.raises(AccumulationStateError, match="Corrupt"):
        await _context(activation)
    await model.AccumulationStrategyState.all().delete()
    with pytest.raises(AccumulationStateError, match="missing or inconsistent"):
        await _context(activation)


@pytest.mark.asyncio
async def test_competing_observation_writes_have_one_winner(accumulation_db):
    activation = await _activation()
    expected = (await _context(activation)).identity
    results = await asyncio.gather(
        save_accumulation_observations(expected, {"winner": 1}, 2000),
        save_accumulation_observations(expected, {"winner": 2}, 2000),
        return_exceptions=True,
    )
    assert sum(isinstance(result, AccumulationIdentity) for result in results) == 1
    assert sum(isinstance(result, AccumulationConflictError) for result in results) == 1
    assert await model.AccumulationStrategyState.all().count() == 1
    current = await _context(activation)
    with pytest.raises(AccumulationConflictError, match="timestamp"):
        await save_accumulation_observations(current.identity, {}, 1500)


@pytest.mark.asyncio
async def test_observation_failure_rolls_back_activation_revision(
    accumulation_db, monkeypatch
):
    activation = await _activation()
    expected = (await _context(activation)).identity

    async def fail_write(*args, **kwargs):
        raise OperationalError("simulated disk failure")

    monkeypatch.setattr(model.AccumulationStrategyState, "update_or_create", fail_write)
    with pytest.raises(OperationalError, match="disk failure"):
        await save_accumulation_observations(expected, {}, 2000)
    assert (await _context(activation)).identity == expected
    assert (await _context(activation)).observations is None
    with pytest.raises(AccumulationStateError, match="account scope"):
        await load_accumulation_context(str(activation.id), "other-account")


@pytest.mark.asyncio
async def test_database_read_failure_is_not_empty_state(accumulation_db, monkeypatch):
    activation = await _activation()

    def fail_read(*args, **kwargs):
        raise OperationalError("database unavailable")

    monkeypatch.setattr(model.AccumulationStrategyState, "get_or_none", fail_read)
    with pytest.raises(OperationalError, match="unavailable"):
        await _context(activation)


@pytest.mark.asyncio
async def test_journal_deduplicates_candles_and_retains_placement_links(
    accumulation_db,
):
    activation = await _activation()
    values = dict(
        activation=activation,
        generation=activation.generation,
        strategy_version_id=activation.strategy_version_id,
        observation_epoch=0,
        signal_close_ms=2000,
        expires_at_ms=3000,
        signal_price="97",
        signal_atr="2",
        unresolved_slot=activation.id,
    )
    opportunity = await model.AccumulationOpportunity.create(**values)
    with pytest.raises(IntegrityError):
        await model.AccumulationOpportunity.create(
            **{**values, "unresolved_slot": None}
        )
    with pytest.raises(IntegrityError):
        await model.AccumulationOpportunity.create(
            **{**values, "signal_close_ms": 3000}
        )
    placement = await model.PlacementIntent.create(
        operation_id="attempt-1",
        exchange_name="test",
        symbol="BTC/USDC",
        action="buy",
        side="buy",
        order_type="market",
        state="unknown",
    )
    await model.AccumulationAttempt.create(opportunity=opportunity, placement=placement)
    with pytest.raises(IntegrityError):
        await model.AccumulationAttempt.create(
            opportunity=opportunity, placement=placement
        )
    with pytest.raises(IntegrityError):
        await placement.delete()
    with pytest.raises(IntegrityError):
        await opportunity.delete()
    await model.AccumulationActivation.filter(id=activation.id).update(
        strategy_version_id=None
    )
    with pytest.raises(PermissionError, match="accumulation"):
        await delete_custom_strategy("custom_accumulate")


@pytest.mark.asyncio
async def test_snapshot_binds_all_accumulation_identity_fields(accumulation_db):
    activation = await _activation()
    identity = (await _context(activation)).identity
    trade = {
        "symbol": "BTC/USDC",
        "lifecycle_mode": "accumulation",
        "accumulation_identity": identity.to_dict(),
    }
    snapshot = LifecycleSnapshotIdentity.from_trade(trade, {})
    assert LifecycleSnapshotIdentity.from_dict(snapshot.to_dict()) == snapshot
    for field, value in {
        "account_scope": "other",
        "generation": "11111111-1111-4111-8111-111111111111",
        "state": "paused",
        "explicitly_paused": False,
        "strategy_version_id": 99,
        "strategy_slug": "other",
        "strategy_version": 2,
        "observation_epoch": 1,
        "baseline_close_ms": 2000,
        "revision": 1,
        "consumption_revision": 1,
    }.items():
        changed = replace(identity, **{field: value})
        assert not snapshots_match(
            snapshot, {**trade, "accumulation_identity": changed.to_dict()}, {}
        )
    with pytest.raises(AccumulationStateError):
        LifecycleSnapshotIdentity.from_trade(
            {"symbol": "BTC/USDC", "lifecycle_mode": "accumulation"}, {}
        )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1e1000000", 1.25, "bad"])
def test_money_rejects_nonfinite_negative_and_float_values(value):
    with pytest.raises(AccumulationStateError):
        canonical_decimal(value)


def test_exact_decimals_observation_bounds_and_legacy_modes():
    assert (
        canonical_decimal("0.123456789123456789123456789")
        == "0.123456789123456789123456789"
    )
    assert parse_lifecycle_mode(None) == "classic_dca"
    assert parse_lifecycle_mode("") == "classic_dca"
    with pytest.raises(ValueError):
        parse_lifecycle_mode("mystery")
    for value in ({"bad": float("nan")}, {"too_large": "x" * 32768}, []):
        with pytest.raises(AccumulationStateError):
            encode_observations(value)
    for raw, schema in (("{}", 2), ("null", 1), ('{"x":NaN}', 1)):
        with pytest.raises(AccumulationStateError):
            decode_observations(raw, schema)


def test_legacy_snapshot_roundtrip_and_explicit_unknown_mode():
    old = LifecycleSnapshotIdentity.from_trade({"symbol": "BTC/USDC"}, {}).to_dict()
    old.pop("lifecycle_mode")
    old.pop("accumulation_identity")
    expected = LifecycleSnapshotIdentity.from_dict(old)
    assert snapshots_match(
        expected, {"symbol": "BTC/USDC", "lifecycle_mode": "classic_dca"}, {}
    )
    with pytest.raises(ValueError):
        LifecycleSnapshotIdentity.from_dict({**old, "lifecycle_mode": "unknown"})
