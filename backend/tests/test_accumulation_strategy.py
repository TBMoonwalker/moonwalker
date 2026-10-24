"""Deterministic market, sizing, rearming and pinned-candidate regression tests."""

import asyncio
import json
from dataclasses import asdict, replace
from decimal import Decimal, localcontext
from unittest.mock import AsyncMock
from uuid import uuid4

import model
import pytest
import pytest_asyncio
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_evaluation import evaluate_accumulation
from service.accumulation_state import (
    AccumulationConflictError,
    load_accumulation_context,
)
from service.accumulation_strategy import (
    AccumulationCandle,
    AccumulationGuard,
    AccumulationMarket,
    AccumulationObservations,
    AccumulationParameters,
    accumulation_requested_quote,
    accumulation_signal_reason,
    advance_accumulation_observations,
    build_accumulation_strategy_document,
    calculate_accumulation_market,
    canonical_accumulation_priority,
    parse_accumulation_strategy_document,
    rebuild_accumulation_observations,
)
from service.lifecycle_mutation import LifecycleMutationCoordinator
from service.strategy_capability import get_accumulation_strategy_support_error
from service.strategy_runtime import load_accumulation_strategy_version
from service.trading_maintenance import TradingMaintenanceBarrier
from tortoise import Tortoise
from tortoise.exceptions import OperationalError

HOUR = 3_600_000
PARAMETERS = AccumulationParameters()


def _candles():
    values = [
        AccumulationCandle((index + 1) * HOUR, "98", "100", "98", "98")
        for index in range(253)
    ]
    values[-1] = AccumulationCandle(253 * HOUR, "98", "98", "96", "97")
    return values


def _market(close, previous, *, index=254, peak="100", atr="2"):
    return AccumulationMarket(
        index * HOUR,
        str(close),
        str(previous),
        peak,
        atr,
        str(max(Decimal(0), (Decimal(peak) - Decimal(str(close))) / Decimal(atr))),
    )


def _guard():
    return AccumulationGuard(str(uuid4()), 253 * HOUR, "97", "2", 1, 1)


def test_exact_prior_peak_and_wilder_seed_excludes_current_high():
    candles = _candles()
    market = calculate_accumulation_market(candles, PARAMETERS, close_ms=253 * HOUR)
    assert (Decimal(market.peak), Decimal(market.atr), Decimal(market.severity)) == (
        100,
        2,
        Decimal("1.5"),
    )
    candles[-1] = AccumulationCandle(253 * HOUR, "98", "108", "96", "97")
    market = calculate_accumulation_market(candles, PARAMETERS, close_ms=253 * HOUR)
    with localcontext() as context:
        context.prec = 50
        assert Decimal(market.atr) == (13 * Decimal(2) + 12) / 14
    assert market.peak == "100"


@pytest.mark.parametrize(
    "severity, funds, expected",
    [
        ("1.5", "1000", "20"),
        ("3.5", "1000", "80"),
        ("7.5", "1000", "200"),
        ("20", "1000", "200"),
        ("7.5", "200", "40"),
    ],
)
def test_experimental_spend_formula(severity, funds, expected):
    fraction, amount = accumulation_requested_quote(severity, funds, PARAMETERS)
    assert Decimal(amount) == Decimal(expected)
    assert Decimal(fraction) <= Decimal("0.2")


def test_further_decline_requires_frozen_spacing_without_rebound():
    guard = _guard()
    state = AccumulationObservations(253 * HOUR, 1)
    shallow = _market(96, 97)
    state = advance_accumulation_observations(state, shallow, guard, PARAMETERS)
    assert accumulation_signal_reason(shallow, state, guard, PARAMETERS) == "WAIT_REARM"
    deeper = _market(95, 96, index=255)
    state = advance_accumulation_observations(state, deeper, guard, PARAMETERS)
    assert (
        accumulation_signal_reason(deeper, state, guard, PARAMETERS)
        == "BUY_FURTHER_DECLINE"
    )
    assert (
        Decimal(accumulation_requested_quote(deeper.severity, "1000", PARAMETERS)[1])
        == 50
    )
    assert guard.signal_price == "97" and guard.signal_atr == "2"


def test_recovery_then_fresh_correction_and_stationary_low():
    guard = _guard()
    state = AccumulationObservations(253 * HOUR, 1)
    previous = 97
    reasons = []
    for index, close in enumerate([99, 100, 98, 97, 97], start=254):
        market = _market(close, previous, index=index)
        state = advance_accumulation_observations(state, market, guard, PARAMETERS)
        reasons.append(accumulation_signal_reason(market, state, guard, PARAMETERS))
        previous = close
    assert reasons[-3:] == ["WAIT_DEPTH", "BUY_FRESH_CORRECTION", "WAIT_DECLINE"]
    assert state.high_close == "100" and state.atr_at_high == "2"
    assert state.recovery_ready


def test_new_consumption_resets_only_recovery_and_version_change_keeps_guard():
    guard = _guard()
    state = AccumulationObservations(254 * HOUR, 0, "120", "2", True)
    market = _market(96, 97, index=255)
    state = advance_accumulation_observations(state, market, guard, PARAMETERS)
    assert state.consumption_revision == 1 and state.high_close == "96"
    assert not state.recovery_ready
    changed = replace(PARAMETERS, spacing_atr="2")
    deeper = _market(95, 96, index=256)
    assert accumulation_signal_reason(deeper, state, guard, changed) == "WAIT_REARM"
    assert guard.signal_price == "97"


def test_recovery_can_accumulate_above_original_consumed_price():
    guard = _guard()
    state = AccumulationObservations(254 * HOUR, 1, "106", "2", True)
    market = _market(102, 103, index=255, peak="110")
    assert (
        accumulation_signal_reason(market, state, guard, PARAMETERS)
        == "BUY_FRESH_CORRECTION"
    )


def test_rebase_is_bounded_observation_only_and_ignores_pre_consumption_highs():
    candles = _candles()
    state = rebuild_accumulation_observations(
        candles, PARAMETERS, _guard(), baseline_close_ms=253 * HOUR
    )
    assert state.last_close_ms == 253 * HOUR and state.high_close is None
    with pytest.raises(AccumulationStateError, match="bounded rebase"):
        rebuild_accumulation_observations(
            candles * 3, PARAMETERS, None, baseline_close_ms=253 * HOUR
        )


def test_rebase_reconstructs_only_the_post_consumption_recovery_high():
    candles = _candles()
    candles[-1] = AccumulationCandle(253 * HOUR, "98", "100", "98", "99")
    candles.extend(
        [
            AccumulationCandle(254 * HOUR, "99", "101", "99", "100"),
            AccumulationCandle(255 * HOUR, "100", "100", "96", "97"),
        ]
    )
    guard = replace(_guard(), signal_close_ms=252 * HOUR)
    state = rebuild_accumulation_observations(
        candles, PARAMETERS, guard, baseline_close_ms=255 * HOUR
    )
    assert state.high_close == "100" and Decimal(state.atr_at_high) == 2
    assert state.recovery_ready and state.last_close_ms == 255 * HOUR


@pytest.mark.parametrize("problem", ["short", "gap", "duplicate", "future", "zero_atr"])
def test_missing_or_invalid_market_window_never_uses_fallback(problem):
    candles = _candles()
    if problem == "short":
        candles = candles[1:]
    if problem == "gap":
        candles[100] = replace(candles[100], close_ms=100 * HOUR + 1000)
    if problem == "duplicate":
        candles[100] = candles[99]
    if problem == "future":
        candles[-1] = replace(candles[-1], close_ms=254 * HOUR)
    if problem == "zero_atr":
        candles = [
            AccumulationCandle(row.close_ms, "98", "98", "98", "98") for row in candles
        ]
    with pytest.raises(AccumulationStateError, match="WAIT_DATA"):
        calculate_accumulation_market(candles, PARAMETERS, close_ms=253 * HOUR)


@pytest.mark.parametrize(
    "overrides",
    [
        {"peak_length": True},
        {"atr_length": 101},
        {"entry_atr": "NaN"},
        {"slope": "0"},
        {"min_fraction": "0.3"},
        {"max_fraction": "1.1"},
        {"timeframe": "2minutes"},
        {"extra": 1},
        {"slope": 0.03},
    ],
)
def test_parameter_contract_rejects_ambiguous_or_unsafe_values(overrides):
    with pytest.raises((TypeError, ValueError)):
        AccumulationParameters.from_dict({**asdict(PARAMETERS), **overrides})


def test_capability_contract_and_priority_do_not_use_strategy_specific_settings():
    document = build_accumulation_strategy_document()
    assert parse_accumulation_strategy_document(document) == PARAMETERS
    assert get_accumulation_strategy_support_error(document) is None
    assert get_accumulation_strategy_support_error({"nodes": []}) is not None
    assert Decimal(
        canonical_accumulation_priority(_candles(), close_ms=253 * HOUR)
    ) == Decimal("1.5")
    assert (
        AccumulationParameters(peak_length=1000, atr_length=100).history_length == 1801
    )


@pytest_asyncio.fixture
async def evaluation_db(tmp_path, monkeypatch):
    url = f"sqlite://{tmp_path / 'strategy.sqlite'}"
    await Tortoise.init(db_url=url, modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    monkeypatch.setattr(
        "service.accumulation_evaluation.lifecycle_mutation_coordinator",
        LifecycleMutationCoordinator(TradingMaintenanceBarrier()),
    )
    yield url
    await Tortoise.close_connections()


async def _activation():
    version = await model.StrategyVersion.create(
        strategy_slug="accumulation_dip_v1",
        version=1,
        ir_json=json.dumps(build_accumulation_strategy_document()),
        validation_json="{}",
        explanation="experimental",
    )
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC",
        account_scope="account",
        strategy_version=version,
        state="enabled",
        explicitly_paused=False,
        baseline_close_ms=252 * HOUR,
        observations_initialized=True,
    )
    await model.AccumulationStrategyState.create(
        activation=activation,
        strategy_version=version,
        observation_epoch=0,
        value_json=json.dumps(asdict(AccumulationObservations(252 * HOUR, 0))),
        last_processed_close_ms=252 * HOUR,
    )
    return activation, version


async def _evaluate(activation, *, identity=None, candles=None, **overrides):
    identity = (
        identity
        or (await load_accumulation_context(str(activation.id), "account")).identity
    )
    arguments = dict(
        priority_candles=_candles(),
        now_ms=253 * HOUR + 500,
        usable_quote="1000",
        ask_price="97",
        quote_timestamp_ms=253 * HOUR,
        minimum_quote="5",
    )
    return await evaluate_accumulation(
        identity,
        candles if candles is not None else _candles(),
        **{**arguments, **overrides},
    )


@pytest.mark.asyncio
async def test_candidate_survives_budget_retry_restart_and_new_active_version(
    evaluation_db,
):
    activation, version = await _activation()
    first = await _evaluate(activation, usable_quote=None)
    assert first.reason == "WAIT_BUDGET" and first.opportunity_id
    next_version = await model.StrategyVersion.create(
        strategy_slug=version.strategy_slug,
        version=2,
        ir_json=json.dumps(
            build_accumulation_strategy_document(
                replace(PARAMETERS, min_fraction="0.1")
            )
        ),
        validation_json="{}",
        explanation="new",
    )
    await model.StrategyDefinition.create(
        slug=version.strategy_slug,
        name="Accumulation",
        active_version=next_version.version,
    )
    second = await _evaluate(activation)
    assert second.action == "BUY" and Decimal(second.requested_quote) == 20
    assert second.opportunity_id == first.opportunity_id
    assert second.identity.strategy_version_id == version.id
    assert (
        await load_accumulation_strategy_version(version.id)
    ).parameters.min_fraction == "0.02"
    await Tortoise.close_connections()
    await Tortoise.init(db_url=evaluation_db, modules={"models": ["model"]})
    third = await _evaluate(activation, usable_quote="200")
    assert Decimal(third.requested_quote) == 4 and third.reason == "WAIT_MINIMUM"
    assert third.opportunity_id == first.opportunity_id
    assert await model.AccumulationOpportunity.all().count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"quote_timestamp_ms": 253 * HOUR - 10000}, "WAIT_DATA"),
        ({"quote_timestamp_ms": 254 * HOUR}, "WAIT_DATA"),
        ({"ask_price": "98"}, "WAIT_PRICE"),
        ({"usable_quote": "0"}, "WAIT_BUDGET"),
        ({"minimum_quote": "21"}, "WAIT_MINIMUM"),
        ({"priority_candles": []}, "WAIT_DATA"),
    ],
)
async def test_preflight_waits_without_upsizing_or_forging_priority(
    evaluation_db, overrides, reason
):
    activation, _ = await _activation()
    result = await _evaluate(activation, **overrides)
    assert result.action == "WAIT" and result.reason == reason
    assert result.opportunity_id


@pytest.mark.asyncio
async def test_stale_revision_concurrency_and_write_failure_do_not_duplicate_candidates(
    evaluation_db, monkeypatch
):
    activation, _ = await _activation()
    identity = (await load_accumulation_context(str(activation.id), "account")).identity
    original = model.AccumulationOpportunity.create
    monkeypatch.setattr(
        model.AccumulationOpportunity,
        "create",
        AsyncMock(side_effect=OperationalError("disk failure")),
    )
    with pytest.raises(OperationalError):
        await _evaluate(activation, identity=identity)
    await activation.refresh_from_db()
    assert activation.revision == 0
    monkeypatch.setattr(model.AccumulationOpportunity, "create", original)
    results = await asyncio.gather(
        _evaluate(activation, identity=identity),
        _evaluate(activation, identity=identity),
        return_exceptions=True,
    )
    assert sum(isinstance(value, AccumulationConflictError) for value in results) == 1
    assert await model.AccumulationOpportunity.all().count() == 1


@pytest.mark.asyncio
async def test_missing_state_and_unresolved_order_never_become_fresh_buy(evaluation_db):
    activation, version = await _activation()
    await model.PlacementIntent.create(
        operation_id="pending",
        exchange_name="binance",
        symbol=activation.symbol,
        action="buy",
        side="buy",
        order_type="market",
        state="indeterminate",
    )
    assert (await _evaluate(activation)).reason == "WAIT_ORDER"
    assert await model.AccumulationOpportunity.all().count() == 0
    await model.AccumulationStrategyState.filter(activation=activation).delete()
    with pytest.raises(AccumulationStateError, match="missing or inconsistent"):
        await _evaluate(activation)


@pytest.mark.asyncio
async def test_missed_candles_and_baseline_do_not_backfill_trades(evaluation_db):
    activation, _ = await _activation()
    activation.baseline_close_ms = 253 * HOUR
    await activation.save()
    await model.AccumulationStrategyState.filter(activation=activation).update(
        last_processed_close_ms=253 * HOUR,
        value_json=json.dumps(asdict(AccumulationObservations(253 * HOUR, 0))),
    )
    assert (await _evaluate(activation)).reason == "WAIT_BASELINE"
    later = [replace(row, close_ms=row.close_ms + 2 * HOUR) for row in _candles()]
    assert (
        await _evaluate(activation, candles=later, now_ms=255 * HOUR)
    ).reason == "WAIT_REBASE"
    assert await model.AccumulationOpportunity.all().count() == 0


@pytest.mark.asyncio
async def test_candle_correction_cannot_rewrite_frozen_candidate(evaluation_db):
    activation, _ = await _activation()
    result = await _evaluate(activation)
    candles = _candles()
    candles[-1] = replace(candles[-1], close="96.5")
    assert (await _evaluate(activation, candles=candles)).reason == "WAIT_DATA"
    opportunity = await model.AccumulationOpportunity.get(id=result.opportunity_id)
    assert opportunity.signal_price == "97"


@pytest.mark.asyncio
async def test_equivalent_decimal_spelling_reuses_candidate(evaluation_db):
    activation, _ = await _activation()
    first = await _evaluate(activation)
    candles = [
        replace(
            row,
            open=row.open + ".0",
            high=row.high + ".0",
            low=row.low + ".0",
            close=row.close + ".0",
        )
        for row in _candles()
    ]
    second = await _evaluate(activation, candles=candles)
    assert second.action == "BUY" and second.opportunity_id == first.opportunity_id


@pytest.mark.asyncio
async def test_expiry_at_unchanged_price_does_not_create_another_opportunity(
    evaluation_db,
):
    activation, _ = await _activation()
    first = await _evaluate(activation)
    candles = _candles()[1:] + [AccumulationCandle(254 * HOUR, "97", "98", "96", "97")]
    expired = await _evaluate(
        activation,
        candles=candles,
        priority_candles=candles,
        now_ms=254 * HOUR,
        quote_timestamp_ms=254 * HOUR,
    )
    assert expired.action == "WAIT" and expired.reason == "WAIT_DECLINE"
    assert await model.AccumulationOpportunity.all().count() == 1
    assert first.expires_at_ms == 254 * HOUR


@pytest.mark.asyncio
async def test_consumed_candidate_cannot_buy_again_and_missing_guard_blocks(
    evaluation_db,
):
    activation, version = await _activation()
    first = await _evaluate(activation)
    opportunity = await model.AccumulationOpportunity.get(id=first.opportunity_id)
    from datetime import datetime, timezone

    opportunity.consumed_at = datetime.now(timezone.utc)
    opportunity.status = "consumed"
    await opportunity.save()
    activation.consumption_revision = 1
    activation.execution_guard_json = json.dumps(
        asdict(
            replace(
                _guard(),
                opportunity_id=str(opportunity.id),
                strategy_version_id=version.id,
            )
        )
    )
    await activation.save(
        update_fields=["consumption_revision", "execution_guard_json"]
    )
    assert (await _evaluate(activation)).reason == "WAIT_CONSUMED"
    activation.execution_guard_json = None
    await activation.save(update_fields=["execution_guard_json"])
    with pytest.raises(AccumulationStateError, match="guard is missing"):
        await _evaluate(activation)


@pytest.mark.asyncio
async def test_strategy_document_cannot_run_through_dca_adapter(monkeypatch):
    from service.strategy_runtime import (
        StrategySnapshot,
        evaluate_strategy_graph,
        get_strategy_adapter,
    )

    snapshot = StrategySnapshot(
        "custom_accumulation",
        1,
        build_accumulation_strategy_document(),
        {},
        "experimental",
    )
    monkeypatch.setattr(
        "service.strategy_runtime._load_strategy_snapshot",
        AsyncMock(return_value=snapshot),
    )
    with pytest.raises(AccumulationStateError, match="dedicated runtime"):
        await get_strategy_adapter("custom_accumulation", "1h")
    result = await evaluate_strategy_graph(
        "custom_accumulation", "1h", "BTC/USDC", "buy"
    )
    assert (
        not result.matched
        and result.reason == "accumulation_requires_dedicated_runtime"
    )


@pytest.mark.asyncio
async def test_peak_migration_preserves_pre_evaluator_opportunities_without_guessing(
    evaluation_db,
):
    from service.database import Database

    activation, _ = await _activation()
    first = await _evaluate(activation)
    connection = Tortoise.get_connection("default")
    await connection.execute_script(
        "ALTER TABLE accumulation_opportunities DROP COLUMN signal_peak"
    )
    database = Database()
    database.db_url = evaluation_db
    await database._ensure_accumulation_strategy_schema()
    await database._ensure_accumulation_strategy_schema()
    opportunity = await model.AccumulationOpportunity.get(id=first.opportunity_id)
    assert opportunity.signal_price == "97" and opportunity.signal_peak is None
    assert (await _evaluate(activation)).reason == "WAIT_DATA"


def test_follow_up_sizing_uses_new_decline_not_old_peak_discount():
    from service.accumulation_strategy import accumulation_step_severity

    guard = _guard()
    # Deep below an old peak, but only one more ATR below the previous purchase.
    depth = accumulation_step_severity("95", "96", "2", guard, PARAMETERS)
    fraction, quote = accumulation_requested_quote(depth, "1000", PARAMETERS)
    assert Decimal(fraction) == Decimal("0.02")
    assert Decimal(quote) == Decimal("20")
    # A much larger fresh decline still increases allocation dynamically.
    heavy = accumulation_step_severity("83", "96", "2", guard, PARAMETERS)
    assert Decimal(
        accumulation_requested_quote(heavy, "1000", PARAMETERS)[0]
    ) == Decimal("0.20")


def test_first_csv_dip_and_recovery_do_not_inherit_peak_maximum_size():
    from service.accumulation_strategy import accumulation_step_severity

    for guard, previous, close in [(None, "100", "99"), (_guard(), "106", "101")]:
        depth = accumulation_step_severity(close, previous, "2", guard, PARAMETERS)
        assert Decimal(
            accumulation_requested_quote(depth, "1000", PARAMETERS)[0]
        ) == Decimal("0.02")


def test_exchange_timeframe_resolves_graph_warmup_without_rewriting_saved_graph():
    from service.accumulation_strategy import effective_accumulation_parameters
    from service.shared_accumulation import regime_accumulation_graph

    graph = regime_accumulation_graph()
    saved = parse_accumulation_strategy_document(graph)
    effective = effective_accumulation_parameters(saved, "4h")
    assert saved.timeframe == graph["accumulation"]["timeframe"] == "1h"
    assert effective.timeframe == "4h"
    assert effective.history_length == 310
    assert saved.history_length == 1240
    assert effective_accumulation_parameters(PARAMETERS, "60min").timeframe == "1h"
    with pytest.raises(AccumulationStateError):
        effective_accumulation_parameters(PARAMETERS, "invalid")


def test_timeframe_change_does_not_reuse_smaller_old_atr_spacing():
    guard = _guard()  # Previous hourly ATR 2, anchor 97.
    market = replace(_market(94, 95), atr="8")
    state = AccumulationObservations(market.close_ms, 1)
    assert accumulation_signal_reason(market, state, guard, PARAMETERS) == "WAIT_REARM"
