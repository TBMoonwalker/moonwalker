"""Real-SQLite portfolio rounds, shared reservations and balance coherence."""

import asyncio
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import model
import pytest
import pytest_asyncio
from service.accumulation_accounting import (
    persist_accumulation_order,
    reject_unsubmitted_accumulation_order,
)
from service.accumulation_budget import (
    AccumulationFundingSnapshot,
    capture_accumulation_funding_token,
    usable_accumulation_quote,
)
from service.accumulation_evaluation import evaluate_accumulation
from service.accumulation_portfolio import (
    AccumulationAdmissionInputs,
    AccumulationOffer,
    AccumulationPortfolioCoordinator,
    prepare_accumulation_buy,
)
from service.accumulation_state import load_accumulation_context
from service.accumulation_strategy import (
    AccumulationCandle,
    AccumulationObservations,
    build_accumulation_strategy_document,
)
from service.capital_budget import CapitalBudgetService, load_pending_capital
from service.lifecycle_mutation import LifecycleMutationCoordinator
from service.placement_intents import PlacementIntentService
from service.trading_maintenance import TradingMaintenanceBarrier
from tortoise import Tortoise
from tortoise.exceptions import OperationalError
from tortoise.transactions import in_transaction

HOUR = 3600000
NOW = 253 * HOUR + 1000
CONFIG = {
    "trade_mode": "accumulation",
    "exchange": "binance",
    "dry_run": False,
    "capital_max_fund": 1000,
}


def candles(close="97"):
    rows = [
        AccumulationCandle((i + 1) * HOUR, "98", "100", "98", "98") for i in range(253)
    ]
    rows[-1] = AccumulationCandle(
        253 * HOUR, "98", "98", str(Decimal(close) - 1), close
    )
    return rows


@pytest_asyncio.fixture
async def portfolio_db(tmp_path, monkeypatch):
    url = f"sqlite://{tmp_path / 'portfolio.sqlite'}"
    await Tortoise.init(db_url=url, modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    coordinator = LifecycleMutationCoordinator(TradingMaintenanceBarrier())
    for name in (
        "accumulation_evaluation",
        "accumulation_portfolio",
        "accumulation_accounting",
    ):
        monkeypatch.setattr(
            f"service.{name}.lifecycle_mutation_coordinator", coordinator
        )
    monkeypatch.setattr(CapitalBudgetService, "_lock", asyncio.Lock())
    monkeypatch.setattr(CapitalBudgetService, "_leases", {})
    monkeypatch.setattr(PlacementIntentService, "_lock", asyncio.Lock())
    yield url
    await Tortoise.close_connections()


async def candidate(symbol="BTC/USDC", close="60"):
    version, _ = await model.StrategyVersion.get_or_create(
        strategy_slug="accumulation_dip_v1",
        version=1,
        defaults={
            "ir_json": json.dumps(build_accumulation_strategy_document()),
            "validation_json": "{}",
            "explanation": "test",
        },
    )
    activation = await model.AccumulationActivation.create(
        symbol=symbol,
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
    identity = (await load_accumulation_context(str(activation.id), "account")).identity
    rows = candles(close)
    decision = await evaluate_accumulation(
        identity,
        rows,
        priority_candles=rows,
        now_ms=NOW,
        usable_quote="1000",
        ask_price=close,
        quote_timestamp_ms=NOW,
        minimum_quote="1",
    )
    assert decision.action == "BUY"
    return AccumulationOffer(decision, tuple(rows))


async def inputs(config=CONFIG, *, now=NOW + 5000, free="1000", holds=()):
    return AccumulationAdmissionInputs(
        AccumulationFundingSnapshot(
            "account",
            "binance",
            "USDC",
            free,
            now,
            await capture_accumulation_funding_token(config),
            holds,
        ),
        "1",
        now,
        "1",
    )


async def admit(offer, config=CONFIG, evidence=None, now=NOW + 5000):
    return await prepare_accumulation_buy(
        offer,
        evidence or await inputs(config, now=now),
        config,
        cutoff_ms=now,
        clock_ms=lambda: now,
    )


async def usable(evidence, config=CONFIG, now=NOW + 5000):
    async with CapitalBudgetService._lock:
        async with in_transaction():
            return await usable_accumulation_quote(config, evidence.funding, now_ms=now)


@pytest.mark.asyncio
async def test_severity_ranking_recomputes_spend_and_persists_atomic_reservations(
    portfolio_db,
):
    weak = await candidate("ETH/USDC", "97")
    strong = await candidate()
    clock = [NOW]
    calls = []

    async def provider(offer):
        calls.append(offer.decision.opportunity_id)
        return await inputs(now=clock[0])

    coordinator = AccumulationPortfolioCoordinator(
        CONFIG, provider, clock_ms=lambda: clock[0]
    )
    coordinator.offer(weak.decision, weak.priority_candles)
    coordinator.offer(strong.decision, strong.priority_candles)
    assert await coordinator.run_due() == []
    clock[0] += 5000
    results = await coordinator.run_due()
    assert calls == [strong.decision.opportunity_id, weak.decision.opportunity_id]
    assert [Decimal(row.requested_quote) for row in results] == [200, 16]
    assert all(row.reason == "PREPARED" for row in results)
    assert await model.AccumulationAttempt.all().count() == 2
    assert (
        await model.AccumulationOpportunity.filter(
            unresolved_slot__isnull=False
        ).count()
        == 2
    )
    assert sum((await load_pending_capital()).values()) == 216
    assert await coordinator.run_due() == [] and coordinator.next_cutoff_ms is None
    assert (await admit(strong)).reason == "WAIT_STATE"
    await Tortoise.close_connections()
    await Tortoise.init(db_url=portfolio_db, modules={"models": ["model"]})
    assert sum((await load_pending_capital()).values()) == 216
    row = await model.PlacementIntent.get(operation_id=results[0].operation_id)
    assert row.state == "prepared" and row.submitted_at is None
    assert Decimal(json.loads(row.request_json)["ordersize"]) == 200


@pytest.mark.asyncio
async def test_ties_use_original_creation_time_then_symbol_not_arrival(portfolio_db):
    a, b, c = (
        await candidate("AAA/USDC"),
        await candidate("BBB/USDC"),
        await candidate("CCC/USDC"),
    )
    date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await model.AccumulationOpportunity.all().update(created_at=date)
    await model.AccumulationOpportunity.filter(id=c.decision.opportunity_id).update(
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc)
    )
    clock = [NOW]

    async def provider(_):
        return await inputs(now=clock[0])

    coordinator = AccumulationPortfolioCoordinator(
        CONFIG, provider, clock_ms=lambda: clock[0]
    )
    for offer in (b, c, a, b):
        coordinator.offer(offer.decision, offer.priority_candles)
    clock[0] += 5000
    results = await coordinator.run_due()
    assert [row.opportunity_id for row in results] == [
        c.decision.opportunity_id,
        a.decision.opportunity_id,
        b.decision.opportunity_id,
    ]
    assert [Decimal(row.requested_quote) for row in results] == [200, 160, 128]


@pytest.mark.asyncio
async def test_no_cap_still_enforces_funds_buffers_and_commitments(portfolio_db):
    config = {
        "trade_mode": "accumulation",
        "exchange": "binance",
        "dry_run": False,
        "buy_fund_buffer_pct": 0.1,
    }
    a, b = await candidate(), await candidate("ETH/USDC")
    first = await admit(a, config)
    assert first.reason == "PREPARED"
    # U is principal after the execution buffer, not an extra cash reserve.
    assert Decimal(first.reserved_quote) <= 200
    second = await admit(b, config)
    assert Decimal(second.requested_quote) < Decimal(first.requested_quote)
    assert sum((await load_pending_capital()).values()) <= 360
    assert (await usable(await inputs(config, free="0"), config)) == "0E-8"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem, reason",
    [
        ("stale", "WAIT_BUDGET"),
        ("future", "WAIT_BUDGET"),
        ("account", "WAIT_ACCOUNT"),
        ("currency", "WAIT_ACCOUNT"),
        ("exchange", "WAIT_ACCOUNT"),
        ("minimum", "WAIT_MINIMUM"),
        ("price", "WAIT_PRICE"),
        ("quote", "WAIT_DATA"),
        ("holds", "WAIT_BUDGET"),
        ("zero", "WAIT_BUDGET"),
    ],
)
async def test_bad_preflight_never_creates_placement(portfolio_db, problem, reason):
    offer = await candidate()
    evidence = await inputs()
    if problem in {"stale", "future"}:
        evidence = replace(
            evidence,
            funding=replace(
                evidence.funding,
                observed_at_ms=NOW - 10000 if problem == "stale" else NOW + 5001,
            ),
        )
    elif problem in {"account", "currency", "exchange"}:
        key = {
            "account": "account_scope",
            "currency": "quote_currency",
            "exchange": "exchange_name",
        }[problem]
        evidence = replace(
            evidence, funding=replace(evidence.funding, **{key: "other"})
        )
    elif problem == "minimum":
        evidence = replace(evidence, minimum_quote="201")
    elif problem == "price":
        evidence = replace(evidence, ask_price="61")
    elif problem == "quote":
        evidence = replace(evidence, quote_timestamp_ms=NOW - 10000)
    elif problem == "holds":
        evidence = replace(
            evidence,
            funding=replace(evidence.funding, reflected_holds=(("unknown", "1"),)),
        )
    else:
        evidence = replace(evidence, funding=replace(evidence.funding, free_quote="0"))
    assert (await admit(offer, evidence=evidence)).reason == reason
    assert await model.PlacementIntent.all().count() == 0
    assert await model.AccumulationAttempt.all().count() == 0


@pytest.mark.asyncio
async def test_classic_lease_invalidates_snapshot_and_reduces_next_admission(
    portfolio_db,
):
    offer = await candidate()
    old = await inputs()
    lease, check = await CapitalBudgetService().acquire_order_lease(
        {"symbol": "SOL/USDC", "ordersize": 400}, CONFIG
    )
    assert check.ok
    assert (await admit(offer, evidence=old)).reason == "WAIT_BUDGET"
    result = await admit(offer)
    assert Decimal(result.requested_quote) == 120
    await lease.release()


@pytest.mark.asyncio
async def test_competing_symbols_cannot_spend_the_same_snapshot(portfolio_db):
    a, b = await candidate(), await candidate("ETH/USDC")
    evidence = await inputs()
    results = await asyncio.gather(
        admit(a, evidence=evidence), admit(b, evidence=evidence)
    )
    assert sorted(row.reason for row in results) == ["PREPARED", "WAIT_BUDGET"]
    assert sum((await load_pending_capital()).values()) == 200


@pytest.mark.asyncio
async def test_pause_during_preflight_and_atomic_rollback(portfolio_db, monkeypatch):
    offer = await candidate()
    await model.AccumulationActivation.filter(
        id=offer.decision.identity.activation_id
    ).update(state="paused", revision=2)
    assert (await admit(offer)).reason == "WAIT_STATE"
    await model.AccumulationActivation.filter(
        id=offer.decision.identity.activation_id
    ).update(state="enabled", revision=1)
    monkeypatch.setattr(
        model.AccumulationAttempt,
        "create",
        AsyncMock(side_effect=OperationalError("disk failure")),
    )
    with pytest.raises(OperationalError, match="disk failure"):
        await admit(offer)
    assert await model.PlacementIntent.all().count() == 0
    row = await model.AccumulationOpportunity.get(id=offer.decision.opportunity_id)
    assert row.unresolved_slot is None and row.status == "candidate"


@pytest.mark.asyncio
async def test_partial_fill_counts_cost_once_and_reflected_hold_once(portfolio_db):
    offer = await candidate()
    result = await admit(offer)
    row = await model.PlacementIntent.get(operation_id=result.operation_id)
    row.state, row.exchange_order_id = "accepted", "exchange-1"
    await row.save()
    evidence_before_fill = await inputs()
    await persist_accumulation_order(
        row.operation_id,
        {
            "id": "exchange-1",
            "symbol": "BTC/USDC",
            "side": "buy",
            "status": "open",
            "filled": "2",
            "cost": "100",
            "fees": [],
            "timestamp": NOW + 5000,
        },
        account_scope="account",
        exchange_name="binance",
    )
    assert await usable(evidence_before_fill) is None
    assert (await load_pending_capital())[row.operation_id] == 100
    usage = await CapitalBudgetService()._load_usage(CONFIG)
    assert usage.funds_locked == 100 and usage.durable_pending_quote == 100
    evidence = await inputs(free="900")
    assert Decimal(await usable(evidence)) == 800
    reflected = await inputs(free="800", holds=((row.operation_id, "100"),))
    assert Decimal(await usable(reflected)) == 800
    invalid = await inputs(free="800", holds=((row.operation_id, "101"),))
    assert await usable(invalid) is None


@pytest.mark.asyncio
async def test_expired_unknown_order_keeps_commitment_and_prepared_rejection_releases(
    portfolio_db,
):
    a, b = await candidate(), await candidate("ETH/USDC")
    first, second = await admit(a), await admit(b)
    await model.PlacementIntent.filter(operation_id=first.operation_id).update(
        state="indeterminate"
    )
    await model.AccumulationOpportunity.filter(id=a.decision.opportunity_id).update(
        expires_at_ms=NOW - 1
    )
    assert sum((await load_pending_capital()).values()) == 360
    await reject_unsubmitted_accumulation_order(
        second.operation_id, account_scope="account", exchange_name="binance"
    )
    assert sum((await load_pending_capital()).values()) == 200
    row = await model.AccumulationOpportunity.get(id=a.decision.opportunity_id)
    assert row.unresolved_slot is not None


@pytest.mark.asyncio
async def test_accumulation_has_no_classic_safety_reserve_and_unknown_basis_blocks(
    portfolio_db,
):
    await model.OpenTrades.create(
        symbol="BTC/USDC",
        lifecycle_mode="accumulation",
        cost=1,
        accumulation_remaining_cost="100",
    )
    await model.OpenTrades.create(symbol="ETH/USDC", cost=50, so_count=1)
    config = {**CONFIG, "capital_reserve_safety_orders": True, "mstc": 5, "bo": 10}
    usage = await CapitalBudgetService()._load_usage(config)
    assert usage.funds_locked == 150 and usage.open_trade_reserve == 40
    await model.OpenTrades.filter(symbol="BTC/USDC").update(
        accumulation_remaining_cost=None
    )
    assert (await CapitalBudgetService()._load_usage(config)).unavailable_reason
    assert await usable(await inputs(config), config) is None


@pytest.mark.asyncio
async def test_rejected_candidate_does_not_block_lower_rank_and_late_offer_waits(
    portfolio_db,
):
    a, b, late = (
        await candidate(),
        await candidate("ETH/USDC", "97"),
        await candidate("SOL/USDC"),
    )
    clock = [NOW]
    calls = []
    coordinator = None

    async def provider(offer):
        calls.append(offer.decision.opportunity_id)
        if len(calls) == 1:
            clock[0] += 1
            coordinator.offer(late.decision, late.priority_candles)
            return replace(await inputs(now=clock[0]), minimum_quote="2000")
        return await inputs(now=clock[0])

    coordinator = AccumulationPortfolioCoordinator(
        CONFIG, provider, clock_ms=lambda: clock[0]
    )
    coordinator.offer(b.decision, b.priority_candles)
    coordinator.offer(a.decision, a.priority_candles)
    clock[0] += 5000
    results = await coordinator.run_due()
    assert [r.reason for r in results] == ["WAIT_MINIMUM", "PREPARED"]
    assert calls == [a.decision.opportunity_id, b.decision.opportunity_id]
    assert await coordinator.run_due() == []
    clock[0] += 5000
    assert (await coordinator.run_due())[
        0
    ].opportunity_id == late.decision.opportunity_id


@pytest.mark.asyncio
async def test_forged_priority_and_hour_rollover_do_not_admit(portfolio_db):
    offer = await candidate()
    forged = replace(offer, decision=replace(offer.decision, priority_score="1000"))
    assert (await admit(forged)).reason == "WAIT_DATA"
    assert (await admit(offer, now=254 * HOUR)).reason == "WAIT_DATA"
    assert await model.PlacementIntent.all().count() == 0


@pytest.mark.asyncio
async def test_quote_expiry_is_checked_after_waiting_for_capital_lock(portfolio_db):
    offer = await candidate()
    evidence = await inputs()
    clock = [NOW + 5000]
    async with CapitalBudgetService._lock:
        task = asyncio.create_task(
            prepare_accumulation_buy(
                offer,
                evidence,
                CONFIG,
                cutoff_ms=clock[0],
                clock_ms=lambda: clock[0],
            )
        )
        await asyncio.sleep(0)
        clock[0] += 10001
    assert (await task).reason == "WAIT_BUDGET"
    assert await model.PlacementIntent.all().count() == 0


@pytest.mark.asyncio
async def test_provider_failure_continues_round_without_holding_locks(portfolio_db):
    first, second = await candidate(), await candidate("ETH/USDC", "97")
    clock = [NOW]
    calls = []

    async def provider(offer):
        calls.append(offer.decision.opportunity_id)
        if len(calls) == 1:
            raise TimeoutError("account data unavailable")
        return await inputs(now=clock[0])

    coordinator = AccumulationPortfolioCoordinator(
        CONFIG, provider, clock_ms=lambda: clock[0]
    )
    for offer in (second, first):
        coordinator.offer(offer.decision, offer.priority_candles)
    clock[0] += 5000
    results = await coordinator.run_due()
    assert [row.reason for row in results] == ["WAIT_DATA", "PREPARED"]
    assert Decimal(results[1].requested_quote) == 20


@pytest.mark.asyncio
async def test_bound_classic_lease_and_durable_intent_are_counted_once(portfolio_db):
    lease, check = await CapitalBudgetService().acquire_order_lease(
        {"symbol": "SOL/USDC", "ordersize": 100},
        CONFIG,
    )
    assert check.ok
    await model.PlacementIntent.create(
        operation_id="classic",
        symbol="SOL/USDC",
        exchange_name="binance",
        action="buy",
        side="buy",
        order_type="limit",
        state="accepted",
        reserved_quote=100,
    )
    await lease.bind_operation("classic")
    evidence = await inputs(free="900", holds=(("classic", "100"),))
    assert Decimal(await usable(evidence)) == 900
    await lease.release()


@pytest.mark.asyncio
async def test_prepared_rejection_allows_new_attempt_for_same_opportunity(portfolio_db):
    offer = await candidate()
    first = await admit(offer)
    await reject_unsubmitted_accumulation_order(
        first.operation_id, account_scope="account", exchange_name="binance"
    )
    context = await load_accumulation_context(
        offer.decision.identity.activation_id, "account"
    )
    # Rejection uses wall time for retry expiry; keep the event valid for this fixture.
    await model.AccumulationOpportunity.filter(id=offer.decision.opportunity_id).update(
        status="retryable", next_retry_at=None
    )
    refreshed = replace(
        offer, decision=replace(offer.decision, identity=context.identity)
    )
    second = await admit(refreshed)
    assert second.reason == "PREPARED" and second.operation_id != first.operation_id
    assert second.opportunity_id == first.opportunity_id
    assert await model.AccumulationAttempt.all().count() == 2
    assert sum((await load_pending_capital()).values()) == 200


@pytest.mark.asyncio
async def test_admission_does_not_invert_generic_journal_and_database_locks(
    portfolio_db,
):
    offer = await candidate()
    # A classic writer may own this lock while waiting for the SQLite connection.
    async with PlacementIntentService._lock:
        result = await asyncio.wait_for(admit(offer), timeout=2)
    assert result.reason == "PREPARED"


@pytest.mark.asyncio
async def test_demo_mode_prepares_durable_exchange_placement(
    portfolio_db,
):
    offer = await candidate()
    result = await admit(offer, {**CONFIG, "dry_run": True})
    assert result.reason == "PREPARED"
    assert await model.PlacementIntent.all().count() == 1
    assert (
        await model.AccumulationOpportunity.filter(
            unresolved_slot__isnull=False
        ).count()
        == 1
    )


@pytest.mark.asyncio
async def test_changing_quote_cannot_implicitly_convert_existing_accumulation_cost(
    portfolio_db,
):
    await model.OpenTrades.create(
        symbol="BTC/USDC",
        lifecycle_mode="accumulation",
        accumulation_remaining_cost="100",
    )
    usage = await CapitalBudgetService()._load_usage({**CONFIG, "currency": "USDT"})
    assert usage.unavailable_reason is not None
