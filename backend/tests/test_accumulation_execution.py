"""Authenticated preflight and single-submission accumulation lifecycle tests."""

import asyncio
import copy
import json
from dataclasses import asdict
from decimal import Decimal
from unittest.mock import AsyncMock

import ccxt.async_support as ccxt
import model
import pytest
import pytest_asyncio
from service.accumulation_accounting import persist_accumulation_order
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_evaluation import evaluate_accumulation
from service.accumulation_exchange import (
    AccumulationExchangeAdapter,
    accumulation_account_scope,
    preflight_accumulation_precision,
)
from service.accumulation_execution import AccumulationBuyExecutor
from service.accumulation_lifecycle import (
    AccumulationLifecycleService,
    AccumulationValidationRequest,
)
from service.accumulation_portfolio import AccumulationOffer, prepare_accumulation_buy
from service.accumulation_recovery import AccumulationPlacementRecovery
from service.accumulation_runtime import AccumulationRuntime, build_accumulation_runtime
from service.accumulation_sales import AccumulationCommandExecutor
from service.accumulation_state import load_accumulation_context
from service.accumulation_strategy import (
    AccumulationObservations,
    AccumulationParameters,
    build_accumulation_strategy_document,
)
from service.capital_budget import CapitalBudgetService, load_pending_capital
from service.exchange import Exchange
from service.exchange_capabilities import (
    ExchangeOrderLookupResult,
    ExchangeOrderLookupStatus,
)
from service.lifecycle_mutation import LifecycleMutationCoordinator
from service.placement_intents import PlacementIntentService
from service.trading_maintenance import TradingMaintenanceBarrier
from tortoise import Tortoise
from tortoise.exceptions import OperationalError

HOUR = 3600000
NOW = 600 * HOUR + 1000
CONFIG = {
    "trade_mode": "accumulation",
    "exchange": "binance",
    "market": "spot",
    "dry_run": False,
    "key": "test-only-api-key",
    "secret": "test-only-secret",
    "currency": "USDC",
    "capital_max_fund": 1000,
}


class Client:
    id = "binance"
    precisionMode = ccxt.TICK_SIZE

    def __init__(self, clock):
        self.clock = clock
        self.markets = {
            "BTC/USDC": {
                "symbol": "BTC/USDC",
                "spot": True,
                "active": True,
                "precision": {"price": 0.01, "amount": 0.001},
                "limits": {"cost": {"min": 5}, "amount": {"min": 0.001, "max": 100}},
            }
        }
        self.balance = {"free": {"USDC": "1000", "BTC": "0"}, "used": {"USDC": "0"}}
        self.open_orders = []
        self.response = None
        self.failure = None
        self.calls = []
        self.ask = "60"
        self.book_timestamp = None
        self.on_submit = None

    def price_to_precision(self, symbol, value):
        return ccxt.decimal_to_precision(
            value,
            ccxt.ROUND,
            self.markets[symbol]["precision"]["price"],
            self.precisionMode,
        )

    def amount_to_precision(self, symbol, value):
        return ccxt.decimal_to_precision(
            value,
            ccxt.TRUNCATE,
            self.markets[symbol]["precision"]["amount"],
            self.precisionMode,
        )

    async def fetch_balance(self):
        return copy.deepcopy(self.balance)

    async def fetch_open_orders(self, symbol):
        return [
            copy.deepcopy(value)
            for value in self.open_orders
            if value.get("symbol") == symbol
        ]

    async def fetch_order_book(self, symbol, limit):
        return {
            "asks": [[self.ask, "100"]],
            "bids": [[self.ask, "100"]],
            "timestamp": self.book_timestamp,
        }

    async def create_market_sell_order(self, symbol, amount, params):
        return await self.create_order(
            symbol, "market", "sell", amount, self.ask, params
        )

    async def create_order(self, symbol, order_type, side, amount, price, params):
        self.calls.append((symbol, order_type, side, amount, price, params))
        assert not CapitalBudgetService._lock.locked()
        if self.on_submit:
            await self.on_submit()
        if self.failure:
            raise self.failure
        if self.response is not None:
            return copy.deepcopy(self.response)
        return {
            "id": "exchange-1",
            "clientOrderId": params["clientOrderId"],
            "symbol": symbol,
            "side": side,
            "status": "closed",
            "filled": amount,
            "cost": str(Decimal(amount) * Decimal(price)),
            "timestamp": self.clock[0],
            "fees": [{"currency": "USDC", "cost": "0"}],
        }

    async def close(self):
        pass


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    url = f"sqlite://{tmp_path / 'execution.sqlite'}"
    await Tortoise.init(db_url=url, modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    barrier = TradingMaintenanceBarrier()
    coordinator = LifecycleMutationCoordinator(barrier)
    for name in (
        "accumulation_evaluation",
        "accumulation_portfolio",
        "accumulation_accounting",
        "accumulation_execution",
        "accumulation_lifecycle",
        "accumulation_sales",
        "accumulation_runtime",
        "accumulation_account_rebind",
        "accumulation_repair",
    ):
        monkeypatch.setattr(
            f"service.{name}.lifecycle_mutation_coordinator", coordinator
        )
    monkeypatch.setattr(
        "service.accumulation_execution.trading_maintenance_barrier", barrier
    )
    monkeypatch.setattr(
        "service.accumulation_sales.trading_maintenance_barrier", barrier
    )
    monkeypatch.setattr(
        "service.accumulation_runtime.trading_maintenance_barrier", barrier
    )
    monkeypatch.setattr(CapitalBudgetService, "_lock", asyncio.Lock())
    monkeypatch.setattr(CapitalBudgetService, "_leases", {})
    monkeypatch.setattr(PlacementIntentService, "_lock", asyncio.Lock())
    clock = [NOW]
    config = dict(CONFIG)
    client = Client(clock)
    exchange = Exchange()
    exchange.exchange = client
    monkeypatch.setattr(exchange, "_Exchange__ensure_exchange", AsyncMock())
    monkeypatch.setattr(exchange, "_Exchange__ensure_markets_loaded", AsyncMock())
    monkeypatch.setattr(
        exchange,
        "fetch_market_metadata",
        AsyncMock(return_value=list(client.markets.values())),
    )

    async def history(*args, **kwargs):
        count = kwargs["max_candles"]
        close = (clock[0] // HOUR) * HOUR
        rows = [
            [close - (count - i) * HOUR, "98", "100", "98", "98", "1"]
            for i in range(count)
        ]
        rows[-1] = [close - HOUR, "98", "98", "59", "60", "1"]
        return rows

    monkeypatch.setattr(
        exchange, "get_history_for_symbol_batched", AsyncMock(side_effect=history)
    )
    adapter = AccumulationExchangeAdapter(
        lambda: config, exchange=exchange, clock_ms=lambda: clock[0]
    )
    yield adapter, client, clock, config, url, barrier
    await exchange.close()
    await Tortoise.close_connections()


async def setup_activation(env):
    adapter, client, clock, config, *_ = env
    version = await model.StrategyVersion.create(
        strategy_slug="accumulation_dip_v1",
        version=1,
        ir_json=json.dumps(build_accumulation_strategy_document()),
        validation_json="{}",
        explanation="experimental",
    )
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC",
        account_scope=accumulation_account_scope(config),
        strategy_version=version,
        state="enabled",
        explicitly_paused=False,
        baseline_close_ms=599 * HOUR,
        observations_initialized=True,
    )
    await model.AccumulationStrategyState.create(
        activation=activation,
        strategy_version=version,
        observation_epoch=0,
        value_json=json.dumps(asdict(AccumulationObservations(599 * HOUR, 0))),
        last_processed_close_ms=599 * HOUR,
    )
    return activation, version


async def prepared(env):
    adapter, client, clock, config, *_ = env
    activation, version = await setup_activation(env)
    context = await load_accumulation_context(
        str(activation.id), activation.account_scope
    )
    rows = await adapter.candles(activation.symbol, AccumulationParameters())
    decision = await evaluate_accumulation(
        context.identity,
        rows,
        priority_candles=rows,
        now_ms=clock[0],
        usable_quote="1000",
        ask_price="60",
        quote_timestamp_ms=clock[0],
        minimum_quote="5",
    )
    offer = AccumulationOffer(decision, rows)
    clock[0] += 5000
    admission = await prepare_accumulation_buy(
        offer,
        await adapter.admission_inputs(offer),
        config,
        cutoff_ms=clock[0],
        clock_ms=adapter.clock_ms,
    )
    assert admission.reason == "PREPARED"
    return admission.operation_id


def test_credential_scope_is_stable_opaque_and_changes_with_venue_or_key():
    value = accumulation_account_scope(CONFIG)
    assert CONFIG["key"] not in value and CONFIG["secret"] not in value
    assert accumulation_account_scope({**CONFIG, "secret": "replacement"}) == value
    for field, change in (
        ("key", "other"),
        ("dry_run", True),
        ("sandbox", True),
        ("exchange_hostname", "other.example"),
    ):
        assert accumulation_account_scope({**CONFIG, field: change}) != value
    for field, change in (("market", "swap"), ("key", "")):
        with pytest.raises(AccumulationStateError):
            accumulation_account_scope({**CONFIG, field: change})


@pytest.mark.asyncio
async def test_precision_records_rounding_without_upsizing_or_minimum_topup(env):
    adapter, client, *_ = env
    plan = preflight_accumulation_precision(client, "BTC/USDC", "200", "60.009")
    assert Decimal(plan.limit_price) == 60 and Decimal(plan.amount) == Decimal("3.333")
    assert Decimal(plan.executable_quote) == Decimal("199.98")
    with pytest.raises(AccumulationStateError, match="minimum"):
        preflight_accumulation_precision(client, "BTC/USDC", "5", "60")
    client.markets["BTC/USDC"]["limits"]["amount"]["max"] = 1
    with pytest.raises(AccumulationStateError, match="limits"):
        preflight_accumulation_precision(client, "BTC/USDC", "200", "60")


@pytest.mark.asyncio
async def test_readiness_warms_completed_candles_and_never_buys(env):
    adapter, client, clock, config, *_ = env
    activation, version = await setup_activation(env)
    ready = await adapter.readiness(
        AccumulationValidationRequest(
            str(activation.id),
            activation.symbol,
            activation.account_scope,
            version.id,
            activation.revision,
            0,
            activation.baseline_close_ms,
        )
    )
    assert ready.baseline_close_ms == 600 * HOUR
    assert ready.observations["last_close_ms"] == 600 * HOUR
    assert client.calls == [] and await model.PlacementIntent.all().count() == 0
    kwargs = adapter.exchange.get_history_for_symbol_batched.call_args.kwargs
    assert kwargs["max_candles"] == 505 and kwargs["until"] == 600 * HOUR - 1


@pytest.mark.asyncio
async def test_new_activation_does_not_need_unowned_base_asset_in_balance(env):
    adapter, client, *_ = env
    del client.balance["free"]["BTC"]
    operation = await prepared(env)
    assert operation and not client.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem", ["ask", "balance", "external", "inactive", "quote", "future"]
)
async def test_unavailable_or_unowned_market_evidence_blocks_preflight(env, problem):
    adapter, client, clock, config, *_ = env
    await setup_activation(env)
    if problem == "ask":
        client.ask = None
    elif problem == "balance":
        client.balance["timestamp"] = clock[0] - 10001
    elif problem == "external":
        client.open_orders = [{"id": "external", "symbol": "BTC/USDC", "side": "sell"}]
    elif problem == "inactive":
        client.markets["BTC/USDC"]["active"] = False
    elif problem == "quote":
        del client.balance["free"]["USDC"]
    else:
        client.book_timestamp = clock[0] + 1
    with pytest.raises(AccumulationStateError):
        await adapter.read_inputs("BTC/USDC", config)
    assert not client.calls


@pytest.mark.asyncio
async def test_owned_base_shortfall_blocks_and_surplus_is_not_adopted(env):
    adapter, client, _, config, *_ = env
    activation, _ = await setup_activation(env)
    holding = await model.OpenTrades.create(
        symbol="BTC/USDC",
        lifecycle_mode="accumulation",
        accumulation_net_quantity="2",
        accumulation_remaining_cost="100",
    )
    activation.holding_id = holding.id
    await activation.save()
    client.balance["free"]["BTC"] = "1"
    with pytest.raises(AccumulationStateError, match="missing or encumbered"):
        await adapter.read_inputs(activation.symbol, config)
    client.balance["free"]["BTC"] = "3"
    assert (
        await adapter.read_inputs(activation.symbol, config)
    ).funding.free_quote == "1000"
    await holding.refresh_from_db()
    assert holding.accumulation_net_quantity == "2"


@pytest.mark.asyncio
async def test_single_submission_accounts_exact_fill_and_duplicate_call_does_not_buy(
    env,
):
    adapter, client, _, _, url, *_ = env
    operation = await prepared(env)
    executor = AccumulationBuyExecutor(adapter)
    result = await executor.execute(operation)
    assert result.state == "completed"
    assert len(client.calls) == 1 and client.calls[0][5]["timeInForce"] == "IOC"
    holding = await model.OpenTrades.get(symbol="BTC/USDC")
    assert holding.accumulation_net_quantity == "3.333"
    assert Decimal(holding.accumulation_remaining_cost) == Decimal("199.98")
    row = await model.PlacementIntent.get(operation_id=operation)
    request = json.loads(row.request_json)
    metadata = json.loads(request["metadata_json"])["accumulation"]
    assert Decimal(request["ordersize"]) == 200 and Decimal(
        metadata["executable_quote"]
    ) == Decimal("199.98")
    assert await load_pending_capital() == {}
    await Tortoise.close_connections()
    await Tortoise.init(db_url=url, modules={"models": ["model"]})
    assert (await executor.execute(operation)).reason == "ALREADY_CLAIMED"
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_concurrent_execution_has_one_wire_effect(env):
    adapter, client, *_ = env
    operation = await prepared(env)
    results = await asyncio.gather(
        *(AccumulationBuyExecutor(adapter).execute(operation) for _ in range(2))
    )
    assert len(client.calls) == 1
    assert any(result.state == "completed" for result in results)
    assert await model.TradeExecutions.all().count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["pause", "expired", "quote", "funds", "precision"])
async def test_pre_submission_changes_reject_without_releasing_unknown_effects(
    env, problem
):
    adapter, client, clock, config, *_ = env
    operation = await prepared(env)
    if problem == "pause":
        await model.AccumulationActivation.all().update(
            state="paused", explicitly_paused=True, revision=100
        )
    elif problem == "expired":
        clock[0] = 601 * HOUR
    elif problem == "quote":
        client.ask = "61"
    elif problem == "funds":
        client.balance["free"]["USDC"] = "100"
    else:
        client.markets["BTC/USDC"]["limits"]["cost"]["min"] = 201
    result = await AccumulationBuyExecutor(adapter).execute(operation)
    assert result.state == "rejected" and not client.calls
    assert await load_pending_capital() == {}
    row = await model.AccumulationOpportunity.all().first()
    assert row.unresolved_slot is None and row.consumed_at is None


@pytest.mark.asyncio
async def test_account_rotation_blocks_before_exchange_submission(env):
    adapter, client, _, config, *_ = env
    operation = await prepared(env)
    config["key"] = "replacement-key"
    result = await AccumulationBuyExecutor(adapter).execute(operation)
    assert result.state == "prepared" and result.reason == "WAIT_ACCOUNT"
    assert sum((await load_pending_capital()).values()) == 200
    assert not client.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("demo", [False, True])
async def test_unknown_response_is_retained_and_late_fill_reconciles_once(
    env, monkeypatch, demo
):
    env[3]["dry_run"] = demo
    adapter, client, clock, config, *_ = env
    operation = await prepared(env)
    client.failure = ccxt.RequestTimeout("lost response")
    result = await AccumulationBuyExecutor(adapter).execute(operation)
    assert result.state == "indeterminate" and len(client.calls) == 1
    assert sum((await load_pending_capital()).values()) == 200
    assert (
        await AccumulationBuyExecutor(adapter).execute(operation)
    ).reason == "ALREADY_CLAIMED"
    row = await model.PlacementIntent.get(operation_id=operation)
    evidence = {
        "id": "late",
        "clientOrderId": row.client_order_id,
        "symbol": row.symbol,
        "side": "buy",
        "status": "canceled",
        "filled": "1",
        "cost": "60",
        "timestamp": clock[0],
        "fees": [{"currency": "USDC", "cost": "0"}],
    }
    monkeypatch.setattr(
        adapter.exchange,
        "lookup_spot_order",
        AsyncMock(
            return_value=ExchangeOrderLookupResult(
                ExchangeOrderLookupStatus.FOUND, evidence
            )
        ),
    )
    recovery = AccumulationPlacementRecovery(adapter.exchange, adapter.account_scope)
    assert await recovery.reconcile(row, config) == "completed"
    assert await model.TradeExecutions.all().count() == 1
    assert len(client.calls) == 1
    assert await load_pending_capital() == {}


@pytest.mark.asyncio
async def test_cancellation_after_claim_keeps_identity_and_reservation(env):
    adapter, client, *_ = env
    operation = await prepared(env)
    started = asyncio.Event()

    async def wait_forever():
        started.set()
        await asyncio.Event().wait()

    client.on_submit = wait_forever
    task = asyncio.create_task(AccumulationBuyExecutor(adapter).execute(operation))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (
        await model.PlacementIntent.get(operation_id=operation)
    ).state == "submitting"
    assert sum((await load_pending_capital()).values()) == 200
    await AccumulationBuyExecutor(adapter).execute(operation)
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_bad_acknowledgement_keeps_journal_without_invented_fill(env):
    adapter, client, *_ = env
    operation = await prepared(env)
    client.response = {"id": "ack-only"}
    result = await AccumulationBuyExecutor(adapter).execute(operation)
    assert result.state == "accepted" and result.reason == "WAIT_RECONCILIATION"
    assert await model.OpenTrades.all().count() == 0
    assert sum((await load_pending_capital()).values()) == 200


@pytest.mark.asyncio
async def test_fee_incomplete_partial_fill_retains_commitment(env):
    adapter, client, clock, config, *_ = env
    operation = await prepared(env)
    client.response = {
        "id": "partial",
        "symbol": "BTC/USDC",
        "side": "buy",
        "status": "canceled",
        "filled": "1",
        "cost": "60",
        "timestamp": clock[0],
    }
    result = await AccumulationBuyExecutor(adapter).execute(operation)
    assert result.state == "accepted"
    assert sum((await load_pending_capital()).values()) == 140
    assert (await model.AccumulationOpportunity.all().first()).consumed_at is not None
    await persist_accumulation_order(
        operation,
        {**client.response, "fees": [{"currency": "USDC", "cost": "0.1"}]},
        account_scope=accumulation_account_scope(config),
        exchange_name="binance",
    )
    assert Decimal(
        (await model.OpenTrades.all().first()).accumulation_remaining_cost
    ) == Decimal("60.1")
    assert await load_pending_capital() == {}


@pytest.mark.asyncio
async def test_accounting_failure_keeps_raw_ack_for_recovery(env, monkeypatch):
    adapter, client, *_ = env
    operation = await prepared(env)
    monkeypatch.setattr(
        model.AccumulationFillCheckpoint,
        "update_or_create",
        AsyncMock(side_effect=OperationalError("disk failure")),
    )
    with pytest.raises(OperationalError):
        await AccumulationBuyExecutor(adapter).execute(operation)
    row = await model.PlacementIntent.get(operation_id=operation)
    assert row.state == "accepted" and json.loads(row.result_json)["id"] == "exchange-1"
    assert await model.OpenTrades.all().count() == 0
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_pending_exchange_holds_are_verified_and_unaccounted_fills_block(env):
    adapter, client, clock, config, *_ = env
    operation = await prepared(env)
    row = await model.PlacementIntent.get(operation_id=operation)
    row.state, row.exchange_order_id = "accepted", "pending"
    await row.save()
    order = {
        "id": "pending",
        "clientOrderId": row.client_order_id,
        "symbol": row.symbol,
        "side": "buy",
        "status": "open",
        "filled": "0",
        "cost": "0",
        "remaining": "3.333",
        "price": "60",
        "timestamp": clock[0],
        "fees": [],
    }
    client.open_orders = [order]
    client.balance["free"]["USDC"] = "800.02"
    client.balance["used"]["USDC"] = "199.98"
    snapshot = await adapter.read_inputs(row.symbol, config)
    assert snapshot.funding.reflected_holds == ((operation, "199.980"),)
    order.update(filled="1", cost="60", remaining="2.333")
    with pytest.raises(AccumulationStateError, match="Unaccounted fill"):
        await adapter.read_inputs(row.symbol, config)
    # An absent acknowledged order is uncertainty, not proof that its funds are free.
    client.open_orders = []
    with pytest.raises(AccumulationStateError, match="reconciliation"):
        await adapter.read_inputs(row.symbol, config)


@pytest.mark.asyncio
async def test_open_order_hold_must_agree_with_balance_used(env):
    adapter, client, clock, config, *_ = env
    operation = await prepared(env)
    row = await model.PlacementIntent.get(operation_id=operation)
    row.state, row.exchange_order_id = "accepted", "pending"
    await row.save()
    client.open_orders = [
        {
            "id": "pending",
            "symbol": row.symbol,
            "side": "buy",
            "status": "open",
            "filled": "0",
            "cost": "0",
            "remaining": "3.333",
            "price": "60",
            "timestamp": clock[0],
        }
    ]
    with pytest.raises(AccumulationStateError, match="disagree"):
        await adapter.read_inputs(row.symbol, config)


@pytest.mark.asyncio
async def test_completed_candle_gap_or_forming_only_history_blocks(env, monkeypatch):
    adapter, _, clock, *_ = env
    original = adapter.exchange.get_history_for_symbol_batched.side_effect

    async def broken(*args, **kwargs):
        rows = await original(*args, **kwargs)
        rows[-2][0] -= HOUR
        return rows

    monkeypatch.setattr(
        adapter.exchange,
        "get_history_for_symbol_batched",
        AsyncMock(side_effect=broken),
    )
    with pytest.raises(AccumulationStateError):
        await adapter.candles("BTC/USDC", AccumulationParameters())
    assert adapter.exchange.exchange.calls == []


@pytest.mark.asyncio
async def test_readiness_rejects_pause_while_fetching_history(env, monkeypatch):
    adapter, client, clock, config, *_ = env
    activation, version = await setup_activation(env)
    original = adapter.exchange.get_history_for_symbol_batched.side_effect

    async def changed(*args, **kwargs):
        await model.AccumulationActivation.filter(id=activation.id).update(
            revision=100, state="paused"
        )
        return await original(*args, **kwargs)

    monkeypatch.setattr(
        adapter.exchange,
        "get_history_for_symbol_batched",
        AsyncMock(side_effect=changed),
    )
    with pytest.raises(AccumulationStateError, match="changed during readiness"):
        await adapter.readiness(
            AccumulationValidationRequest(
                str(activation.id),
                activation.symbol,
                activation.account_scope,
                version.id,
                activation.revision,
                0,
                activation.baseline_close_ms,
            )
        )
    assert client.calls == []


@pytest.mark.asyncio
async def test_zero_fill_settlement_releases_without_consumption(env):
    adapter, client, clock, *_ = env
    operation = await prepared(env)
    client.response = {
        "id": "zero",
        "symbol": "BTC/USDC",
        "side": "buy",
        "status": "canceled",
        "filled": "0",
        "cost": "0",
        "timestamp": clock[0],
    }
    result = await AccumulationBuyExecutor(adapter).execute(operation)
    assert result.state == "completed" and await load_pending_capital() == {}
    assert await model.OpenTrades.all().count() == 0
    row = await model.AccumulationOpportunity.all().first()
    assert row.consumed_at is None and row.unresolved_slot is None
    await AccumulationBuyExecutor(adapter).execute(operation)
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_claim_write_failure_cannot_reach_the_exchange(env, monkeypatch):
    adapter, client, *_ = env
    operation = await prepared(env)
    original = model.PlacementIntent.save

    async def fail_claim(self, *args, **kwargs):
        if self.state == "submitting":
            raise OperationalError("disk failure")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(model.PlacementIntent, "save", fail_claim)
    with pytest.raises(OperationalError):
        await AccumulationBuyExecutor(adapter).execute(operation)
    row = await model.PlacementIntent.get(operation_id=operation)
    assert row.state == "prepared" and row.submitted_at is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_maintenance_blocks_new_execution_and_drains_inflight_submission(env):
    adapter, client, _, _, _, barrier = env
    operation = await prepared(env)
    executor = AccumulationBuyExecutor(adapter)
    async with barrier.maintenance():
        assert (await executor.execute(operation)).reason == "WAIT_MAINTENANCE"
    assert not client.calls
    started, release, maintained = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def wait_submission():
        started.set()
        await release.wait()

    async def maintenance():
        async with barrier.maintenance():
            maintained.set()

    client.on_submit = wait_submission
    task = asyncio.create_task(executor.execute(operation))
    await asyncio.wait_for(started.wait(), timeout=2)
    maintenance_task = asyncio.create_task(maintenance())
    await asyncio.sleep(0)
    assert not maintained.is_set()
    release.set()
    assert (await task).state == "completed"
    await maintenance_task
    assert maintained.is_set()


@pytest.mark.asyncio
async def test_provider_network_failure_is_wait_not_a_wire_retry(env, monkeypatch):
    adapter, client, *_ = env
    operation = await prepared(env)
    monkeypatch.setattr(
        client, "fetch_balance", AsyncMock(side_effect=ccxt.RequestTimeout("offline"))
    )
    result = await AccumulationBuyExecutor(adapter).execute(operation)
    assert result.state == "prepared" and result.reason == "WAIT_DATA"
    assert client.calls == [] and sum((await load_pending_capital()).values()) == 200


@pytest.mark.asyncio
async def test_lifecycle_uses_adapter_readiness_and_persists_baseline_without_buying(
    env,
):
    adapter, client, _, config, *_ = env
    version = await model.StrategyVersion.create(
        strategy_slug="accumulation_dip_v1",
        version=1,
        ir_json=json.dumps(build_accumulation_strategy_document()),
        validation_json="{}",
        explanation="test",
    )
    service = AccumulationLifecycleService(adapter.readiness)
    scope = accumulation_account_scope(config)
    staged = await service.stage_activation(
        symbol="BTC/USDC",
        account_scope=scope,
        strategy_version_id=version.id,
        source="asap",
        operation_id="activate-adapter",
    )
    assert staged.state == "validating"
    result = await service.complete_rebase("activate-adapter", account_scope=scope)
    assert result.state == "enabled" and result.status == "applied"
    activation = await model.AccumulationActivation.get(symbol="BTC/USDC")
    assert (
        activation.baseline_close_ms == 600 * HOUR
        and not activation.observations_initialized
    )
    assert not client.calls and await model.OpenTrades.all().count() == 0


@pytest.mark.asyncio
async def test_budget_config_change_during_preflight_cannot_claim_old_limit(
    env, monkeypatch
):
    adapter, client, _, config, *_ = env
    operation = await prepared(env)
    original = adapter.read_inputs

    async def read_and_change(*args):
        snapshot = await original(*args)
        config["capital_max_fund"] = 10
        return snapshot

    monkeypatch.setattr(adapter, "read_inputs", read_and_change)
    result = await AccumulationBuyExecutor(adapter).execute(operation)
    assert result.state == "rejected" and result.reason == "WAIT_STATE"
    assert not client.calls


@pytest.mark.asyncio
async def test_unknown_order_symbol_is_not_treated_as_an_empty_order_list(
    env, monkeypatch
):
    adapter, client, _, config, *_ = env
    monkeypatch.setattr(
        client, "fetch_open_orders", AsyncMock(return_value=[{"id": "unknown"}])
    )
    with pytest.raises(AccumulationStateError, match="Open-order evidence is invalid"):
        await adapter.read_inputs("BTC/USDC", config)


@pytest.mark.asyncio
@pytest.mark.parametrize("ask", [["0", "100"], ["60", "0"], ["60"]])
async def test_zero_or_missing_executable_depth_cannot_admit_a_buy(
    env, monkeypatch, ask
):
    adapter, client, _, config, *_ = env
    monkeypatch.setattr(
        client, "fetch_order_book", AsyncMock(return_value={"asks": [ask]})
    )
    with pytest.raises(AccumulationStateError):
        await adapter.read_inputs("BTC/USDC", config)


async def manual_sale(env, action="close", *, paused=False):
    adapter, client, *_ = env
    buy_id = await prepared(env)
    assert (await AccumulationBuyExecutor(adapter).execute(buy_id)).state == "completed"
    activation = await model.AccumulationActivation.get(symbol="BTC/USDC")
    holding = await model.OpenTrades.get(id=activation.holding_id)
    client.balance["free"]["BTC"] = holding.accumulation_net_quantity
    if paused:
        activation.state, activation.explicitly_paused = "paused", True
        await activation.save()
    request = dict(
        symbol=activation.symbol,
        action=action,
        operation_id="operator-sale",
        expected_revision=activation.revision,
    )
    if action == "sell_partial":
        request["quantity"] = "1"
    await AccumulationLifecycleService().submit(
        request, account_scope=activation.account_scope
    )
    return activation, holding


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,paused", [("close", False), ("sell_partial", False), ("sell_partial", True)]
)
@pytest.mark.parametrize("demo", [False, True])
async def test_manual_sale_uses_owned_quantity_and_restores_intended_state(
    env, action, paused, demo
):
    env[3]["dry_run"] = demo
    adapter, client, *_ = env
    activation, holding = await manual_sale(env, action, paused=paused)
    quantity = Decimal(holding.accumulation_net_quantity)
    result = await AccumulationCommandExecutor(adapter).execute("operator-sale")
    assert result.reason == "SETTLED"
    assert len(client.calls) == 2 and client.calls[-1][1:3] == ("market", "sell")
    await activation.refresh_from_db()
    if action == "close":
        assert activation.state == "stopped" and activation.holding_id is None
        assert not await model.OpenTrades.exists()
    else:
        await holding.refresh_from_db()
        assert Decimal(holding.accumulation_net_quantity) == quantity - 1
        assert activation.state == ("paused" if paused else "enabled")
        assert activation.explicitly_paused is paused
    retry = await AccumulationCommandExecutor(adapter).execute("operator-sale")
    assert retry.reason == "ALREADY_APPLIED" and len(client.calls) == 2


@pytest.mark.asyncio
async def test_concurrent_manual_sale_workers_submit_once(env):
    adapter, client, *_ = env
    await manual_sale(env)
    outcomes = await asyncio.gather(
        *(
            AccumulationCommandExecutor(adapter).execute("operator-sale")
            for _ in range(2)
        ),
        return_exceptions=True,
    )
    assert any(getattr(result, "reason", None) == "SETTLED" for result in outcomes)
    assert len(client.calls) == 2
    assert await model.PlacementIntent.filter(side="sell").count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "scope",
        "wallet",
        "external_order",
        "stale",
        "minimum",
        "increase",
        "state_change",
        "maintenance",
    ],
)
async def test_manual_sale_preflight_blocks_without_a_wire_effect(
    env, fault, monkeypatch
):
    adapter, client, clock, config, _, barrier = env
    activation, _ = await manual_sale(env)
    if fault == "scope":
        config["key"] = "other-account"
    elif fault == "wallet":
        client.balance["free"]["BTC"] = "0"
    elif fault == "external_order":
        client.open_orders = [{"symbol": activation.symbol, "id": "unmanaged"}]
    elif fault == "stale":
        client.book_timestamp = clock[0] - 10001
    elif fault == "minimum":
        client.markets[activation.symbol]["limits"]["cost"]["min"] = 10000
    elif fault == "increase":
        monkeypatch.setattr(client, "amount_to_precision", lambda *_: "100")
    elif fault == "state_change":
        original = adapter.sale_inputs

        async def changed(*args):
            value = await original(*args)
            activation.revision += 1
            await activation.save()
            return value

        monkeypatch.setattr(adapter, "sale_inputs", changed)
    if fault == "maintenance":
        async with barrier.maintenance():
            assert (
                await AccumulationCommandExecutor(adapter).execute("operator-sale")
            ).reason == "WAIT_MAINTENANCE"
    elif fault == "minimum":
        assert (
            await AccumulationCommandExecutor(adapter).execute("operator-sale")
        ).reason == "WAIT_MINIMUM"
    else:
        with pytest.raises(AccumulationStateError):
            await AccumulationCommandExecutor(adapter).execute("operator-sale")
    assert len(client.calls) == 1
    assert not await model.PlacementIntent.filter(side="sell").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,filled", [("close", "1"), ("close", "0"), ("sell_partial", "0.5")]
)
async def test_terminal_partial_manual_sale_never_resubmits_remainder(
    env, action, filled
):
    adapter, client, clock, *_ = env
    activation, holding = await manual_sale(env, action)
    client.response = {
        "id": "sale-partial",
        "symbol": activation.symbol,
        "side": "sell",
        "status": "canceled",
        "filled": filled,
        "cost": str(Decimal(filled) * 60),
        "fees": [{"currency": "USDC", "cost": "0"}],
        "timestamp": clock[0],
    }
    result = await AccumulationCommandExecutor(adapter).execute("operator-sale")
    assert result.reason == ("WAIT_REMAINDER" if action == "close" else "SETTLED")
    await activation.refresh_from_db()
    assert activation.state == ("closing" if action == "close" else "enabled")
    await AccumulationCommandExecutor(adapter).execute("operator-sale")
    assert len(client.calls) == 2
    assert await model.OpenTrades.filter(id=holding.id).exists()


@pytest.mark.asyncio
async def test_precision_dust_keeps_close_latched(env):
    adapter, client, *_ = env
    activation, holding = await manual_sale(env)
    holding.accumulation_net_quantity = str(
        Decimal(holding.accumulation_net_quantity) + Decimal("0.0005")
    )
    await holding.save()
    client.balance["free"]["BTC"] = holding.accumulation_net_quantity
    result = await AccumulationCommandExecutor(adapter).execute("operator-sale")
    assert result.reason == "WAIT_REMAINDER"
    await activation.refresh_from_db()
    await holding.refresh_from_db()
    assert activation.state == "closing" and Decimal(
        holding.accumulation_net_quantity
    ) == Decimal("0.0005")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["timeout", "cancelled", "missing_ack", "missing_fees", "accounting"]
)
async def test_manual_sale_uncertainty_recovers_without_resubmission(
    env, failure, monkeypatch
):
    adapter, client, clock, config, *_ = env
    activation, holding = await manual_sale(env)
    quantity = holding.accumulation_net_quantity
    if failure == "timeout":
        client.failure = TimeoutError()
    elif failure == "cancelled":

        async def cancel():
            raise asyncio.CancelledError()

        client.on_submit = cancel
    elif failure == "missing_ack":
        client.response = {}
    elif failure == "missing_fees":
        client.response = {
            "id": "sale-recovery",
            "symbol": activation.symbol,
            "side": "sell",
            "status": "closed",
            "filled": quantity,
            "cost": str(Decimal(quantity) * 60),
            "timestamp": clock[0],
        }
    else:
        monkeypatch.setattr(
            "service.accumulation_sales.persist_accumulation_order",
            AsyncMock(side_effect=OperationalError("rollback")),
        )
    if failure == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await AccumulationCommandExecutor(adapter).execute("operator-sale")
    elif failure == "accounting":
        with pytest.raises(OperationalError):
            await AccumulationCommandExecutor(adapter).execute("operator-sale")
    else:
        assert (
            await AccumulationCommandExecutor(adapter).execute("operator-sale")
        ).reason == "WAIT_RECONCILIATION"
    row = await model.PlacementIntent.get(side="sell")
    assert row.state in {"accepted", "submitting", "indeterminate"}
    report = {
        "id": row.exchange_order_id or "sale-recovery",
        "clientOrderId": row.client_order_id,
        "symbol": activation.symbol,
        "side": "sell",
        "status": "closed",
        "filled": quantity,
        "cost": str(Decimal(quantity) * 60),
        "fees": [{"currency": "USDC", "cost": "0"}],
        "timestamp": clock[0],
    }
    monkeypatch.setattr(
        adapter.exchange,
        "lookup_spot_order",
        AsyncMock(
            return_value=ExchangeOrderLookupResult(
                ExchangeOrderLookupStatus.FOUND, report
            )
        ),
    )
    result = await AccumulationCommandExecutor(adapter).execute("operator-sale")
    assert result.reason == "SETTLED" and len(client.calls) == 2
    await activation.refresh_from_db()
    assert activation.state == "stopped"


@pytest.mark.asyncio
async def test_pause_rejects_prepared_buy_without_cancelling_or_submitting(
    env, monkeypatch
):
    adapter, client, *_ = env
    buy_id = await prepared(env)
    activation = await model.AccumulationActivation.get(symbol="BTC/USDC")
    await AccumulationLifecycleService().submit(
        dict(
            symbol=activation.symbol,
            action="pause",
            operation_id="pause-buy",
            expected_revision=activation.revision,
        ),
        account_scope=activation.account_scope,
    )
    cancel = AsyncMock()
    monkeypatch.setattr(adapter.exchange, "cancel_spot_order", cancel)
    result = await AccumulationCommandExecutor(adapter).execute("pause-buy")
    assert result.reason == "SETTLED"
    assert (await model.PlacementIntent.get(operation_id=buy_id)).state == "rejected"
    assert not client.calls and not cancel.called


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_terminal", [True, False])
async def test_pause_cancellation_waits_for_terminal_lookup_and_accounts_racing_fill(
    env, monkeypatch, cancel_terminal
):
    adapter, client, clock, *_ = env
    buy_id = await prepared(env)
    row = await model.PlacementIntent.get(operation_id=buy_id)
    report = {
        "id": "pending-buy",
        "clientOrderId": row.client_order_id,
        "symbol": row.symbol,
        "side": "buy",
        "status": "open",
        "filled": "0",
        "cost": "0",
        "timestamp": clock[0],
    }
    client.response = report
    await AccumulationBuyExecutor(adapter).execute(buy_id)
    activation = await model.AccumulationActivation.get(symbol=row.symbol)
    await AccumulationLifecycleService().submit(
        dict(
            symbol=row.symbol,
            action="pause",
            operation_id="pause-buy",
            expected_revision=activation.revision,
        ),
        account_scope=activation.account_scope,
    )

    async def lookup(*args, **kwargs):
        return ExchangeOrderLookupResult(
            ExchangeOrderLookupStatus.FOUND, copy.deepcopy(report)
        )

    async def cancel(*args):
        assert (
            await model.PlacementIntent.get(operation_id=buy_id)
        ).reason_code == "accumulation_cancel_requested"
        if cancel_terminal:
            report.update(
                status="canceled",
                filled="1",
                cost="60",
                fees=[{"currency": "USDC", "cost": "0"}],
            )
        return {"status": "canceled"}  # Never sufficient settlement evidence itself.

    monkeypatch.setattr(adapter.exchange, "lookup_spot_order", lookup)
    monkeypatch.setattr(adapter.exchange, "cancel_spot_order", cancel)
    if cancel_terminal:
        assert (
            await AccumulationCommandExecutor(adapter).execute("pause-buy")
        ).reason == "SETTLED"
        holding = await model.OpenTrades.get(symbol=row.symbol)
        assert holding.accumulation_net_quantity == "1"
    else:
        with pytest.raises(AccumulationStateError, match="reconciliation"):
            await AccumulationCommandExecutor(adapter).execute("pause-buy")
        assert (
            await model.PlacementIntent.get(operation_id=buy_id)
        ).state == "accepted"
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_unknown_buy_identity_blocks_pause_without_cancellation(env, monkeypatch):
    adapter, client, *_ = env
    buy_id = await prepared(env)
    client.failure = TimeoutError()
    await AccumulationBuyExecutor(adapter).execute(buy_id)
    activation = await model.AccumulationActivation.get(symbol="BTC/USDC")
    await AccumulationLifecycleService().submit(
        dict(
            symbol=activation.symbol,
            action="pause",
            operation_id="pause-unknown",
            expected_revision=activation.revision,
        ),
        account_scope=activation.account_scope,
    )
    monkeypatch.setattr(
        adapter.exchange,
        "lookup_spot_order",
        AsyncMock(
            return_value=ExchangeOrderLookupResult(ExchangeOrderLookupStatus.NOT_FOUND)
        ),
    )
    cancel = AsyncMock()
    monkeypatch.setattr(adapter.exchange, "cancel_spot_order", cancel)
    with pytest.raises(AccumulationStateError, match="reconciliation"):
        await AccumulationCommandExecutor(adapter).execute("pause-unknown")
    assert not cancel.called
    assert (
        await model.PlacementIntent.get(operation_id=buy_id)
    ).state == "indeterminate"


@pytest.mark.asyncio
async def test_manual_sale_claim_rolls_back_before_exchange_effect(env, monkeypatch):
    adapter, client, *_ = env
    await manual_sale(env)
    monkeypatch.setattr(
        model.AccumulationLifecycleOperation,
        "save",
        AsyncMock(side_effect=OperationalError("transaction rollback")),
    )
    with pytest.raises(OperationalError):
        await AccumulationCommandExecutor(adapter).execute("operator-sale")
    assert len(client.calls) == 1
    assert not await model.PlacementIntent.filter(side="sell").exists()
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id="operator-sale")
    ).placement_id is None


@pytest.mark.asyncio
async def test_full_close_includes_late_buy_fill_before_selecting_sale_quantity(
    env, monkeypatch
):
    adapter, client, clock, *_ = env
    buy_id = await prepared(env)
    row = await model.PlacementIntent.get(operation_id=buy_id)
    report = {
        "id": "pending-buy",
        "clientOrderId": row.client_order_id,
        "symbol": row.symbol,
        "side": "buy",
        "status": "open",
        "filled": "1",
        "cost": "60",
        "fees": [{"currency": "USDC", "cost": "0"}],
        "timestamp": clock[0],
    }
    client.response = report
    await AccumulationBuyExecutor(adapter).execute(buy_id)
    activation = await model.AccumulationActivation.get(symbol=row.symbol)
    await AccumulationLifecycleService().submit(
        dict(
            symbol=row.symbol,
            action="close",
            operation_id="close-late-buy",
            expected_revision=activation.revision,
        ),
        account_scope=activation.account_scope,
    )

    async def lookup(*args, **kwargs):
        return ExchangeOrderLookupResult(
            ExchangeOrderLookupStatus.FOUND, copy.deepcopy(report)
        )

    async def cancel(*args):
        report.update(status="canceled", filled="2", cost="120")
        client.balance["free"]["BTC"] = "2"

    monkeypatch.setattr(adapter.exchange, "lookup_spot_order", lookup)
    monkeypatch.setattr(adapter.exchange, "cancel_spot_order", cancel)
    client.response = None
    result = await AccumulationCommandExecutor(adapter).execute("close-late-buy")
    assert result.reason == "SETTLED"
    assert Decimal(client.calls[-1][3]) == 2
    await activation.refresh_from_db()
    assert activation.state == "stopped"


async def close_with_remainder(env, remainder="1"):
    adapter, client, clock, *_ = env
    activation, holding = await manual_sale(env)
    filled = Decimal(holding.accumulation_net_quantity) - Decimal(remainder)
    client.response = {
        "id": "sale-first",
        "symbol": activation.symbol,
        "side": "sell",
        "status": "canceled",
        "filled": str(filled),
        "cost": str(filled * 60),
        "fees": [{"currency": "USDC", "cost": "0"}],
        "timestamp": clock[0],
    }
    result = await AccumulationCommandExecutor(adapter).execute("operator-sale")
    assert result.reason == "WAIT_REMAINDER"
    await activation.refresh_from_db()
    await holding.refresh_from_db()
    client.balance["free"]["BTC"] = holding.accumulation_net_quantity
    client.response = None
    return activation, holding


async def retry_remainder(
    activation, *, operation_id="retry-sale", previous="operator-sale"
):
    await activation.refresh_from_db()
    return await AccumulationLifecycleService().submit(
        dict(
            symbol=activation.symbol,
            action="retry_close",
            operation_id=operation_id,
            previous_operation_id=previous,
            expected_revision=activation.revision,
        ),
        account_scope=activation.account_scope,
    )


@pytest.mark.asyncio
async def test_explicit_close_retry_sells_only_remainder_and_preserves_history_after_restart(
    env,
):
    adapter, client, _, _, url, *_ = env
    activation, holding = await close_with_remainder(env)
    first = await model.AccumulationLifecycleOperation.get(operation_id="operator-sale")
    first_placement = await model.PlacementIntent.get(id=first.placement_id)
    first_checkpoint = await model.AccumulationFillCheckpoint.get(
        placement=first_placement
    )
    original_evidence = first_checkpoint.evidence_json
    await retry_remainder(activation)
    await Tortoise.close_connections()
    await Tortoise.init(db_url=url, modules={"models": ["model"]})
    assert (
        await AccumulationCommandExecutor(adapter).execute("operator-sale")
    ).reason == "INACTIVE"
    assert len(client.calls) == 2
    assert (
        await AccumulationCommandExecutor(adapter).execute("retry-sale")
    ).reason == "SETTLED"
    assert Decimal(client.calls[-1][3]) == 1
    await activation.refresh_from_db()
    assert activation.state == "stopped" and activation.holding_id is None
    await first.refresh_from_db()
    await first_checkpoint.refresh_from_db()
    assert first.status == "continued" and first.placement_id == first_placement.id
    assert first_checkpoint.evidence_json == original_evidence
    assert (
        await model.AccumulationFillCheckpoint.filter(activation=activation).count()
        == 3
    )
    assert await model.PlacementIntent.filter(side="sell").count() == 2
    assert (
        await model.PlacementIntent.get(
            side="sell", source_operation_id=first_placement.operation_id
        )
    ).state == "completed"
    await AccumulationCommandExecutor(adapter).execute("retry-sale")
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_dust_wait_retains_exact_basis_and_close_until_explicit_retry_is_sellable(
    env,
):
    adapter, client, *_ = env
    activation, holding = await close_with_remainder(env, "0.05")
    before = (
        holding.accumulation_net_quantity,
        holding.accumulation_remaining_cost,
        holding.accumulation_contributed_quote,
        holding.accumulation_disposal_proceeds,
    )
    await retry_remainder(activation)
    result = await AccumulationCommandExecutor(adapter).execute("retry-sale")
    assert result.reason == "WAIT_MINIMUM"
    assert len(client.calls) == 2
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id="retry-sale")
    ).placement_id is None
    await holding.refresh_from_db()
    assert before == (
        holding.accumulation_net_quantity,
        holding.accumulation_remaining_cost,
        holding.accumulation_contributed_quote,
        holding.accumulation_disposal_proceeds,
    )
    await activation.refresh_from_db()
    assert activation.state == "closing"
    client.ask = "100"
    assert (
        await AccumulationCommandExecutor(adapter).execute("retry-sale")
    ).reason == "SETTLED"
    assert Decimal(client.calls[-1][3]) == Decimal("0.05")
    await activation.refresh_from_db()
    assert activation.state == "stopped"


@pytest.mark.asyncio
async def test_subprecision_dust_is_never_rounded_up_or_written_off(env):
    adapter, client, *_ = env
    activation, holding = await close_with_remainder(env, "0.0005")
    await retry_remainder(activation)
    assert (
        await AccumulationCommandExecutor(adapter).execute("retry-sale")
    ).reason == "WAIT_PRECISION"
    await holding.refresh_from_db()
    await activation.refresh_from_db()
    assert Decimal(holding.accumulation_net_quantity) == Decimal("0.0005")
    assert activation.state == "closing" and len(client.calls) == 2


@pytest.mark.asyncio
async def test_partial_fill_of_explicit_retry_requires_another_explicit_command(env):
    adapter, client, clock, *_ = env
    activation, _ = await close_with_remainder(env)
    await retry_remainder(activation)
    client.response = {
        "id": "sale-second",
        "symbol": activation.symbol,
        "side": "sell",
        "status": "canceled",
        "filled": "0.5",
        "cost": "30",
        "fees": [{"currency": "USDC", "cost": "0"}],
        "timestamp": clock[0],
    }
    assert (
        await AccumulationCommandExecutor(adapter).execute("retry-sale")
    ).reason == "WAIT_REMAINDER"
    await AccumulationCommandExecutor(adapter).execute("retry-sale")
    assert len(client.calls) == 3
    await retry_remainder(activation, operation_id="retry-again", previous="retry-sale")
    client.response = None
    client.balance["free"]["BTC"] = "0.5"
    assert (
        await AccumulationCommandExecutor(adapter).execute("retry-again")
    ).reason == "SETTLED"
    assert (
        await model.AccumulationLifecycleOperation.filter(status="continued").count()
        == 2
    )
    assert len(client.calls) == 4


def test_production_runtime_gate_does_not_read_config_or_open_exchange(monkeypatch):
    monkeypatch.setattr(
        "service.accumulation_runtime.ACCUMULATION_RUNTIME_AVAILABLE", False
    )

    def prohibited():
        raise AssertionError("disabled feature must not read credentials")

    assert build_accumulation_runtime(prohibited) is None


@pytest.mark.asyncio
async def test_runtime_rebases_startup_then_buys_only_after_new_candle_and_round(env):
    adapter, client, clock, *_ = env
    activation, _ = await setup_activation(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    await activation.refresh_from_db()
    assert (
        activation.baseline_close_ms == 600 * HOUR and activation.observation_epoch == 1
    )
    await runtime.tick()
    assert not client.calls and not await model.AccumulationOpportunity.exists()
    clock[0] += HOUR
    await runtime.tick()
    assert runtime.status[activation.symbol] == "BUY_OPPORTUNITY"
    assert not client.calls
    clock[0] += 5000
    await runtime.tick()
    assert len(client.calls) == 1
    assert runtime.status[activation.symbol] == "SETTLED"
    holding = await model.OpenTrades.get(symbol=activation.symbol)
    client.balance["free"]["BTC"] = holding.accumulation_net_quantity
    for _ in range(3):
        clock[0] += 5000
        await runtime.tick()
    assert len(client.calls) == 1
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_runtime_wait_needs_new_inputs_instead_of_self_requeue(env, monkeypatch):
    adapter, client, clock, *_ = env
    activation, _ = await setup_activation(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    client.ask = "65"
    reads = AsyncMock(wraps=adapter.read_inputs)
    monkeypatch.setattr(adapter, "read_inputs", reads)
    clock[0] += HOUR
    await runtime.tick()
    assert runtime.status[activation.symbol] == "WAIT_PRICE"
    count = reads.call_count
    for _ in range(3):
        clock[0] += 5000
        await runtime.tick()
    assert reads.call_count == count and not client.calls
    client.ask = "60"
    for _ in range(300):
        runtime.notify(activation.symbol)
    await runtime.tick()
    assert runtime.status[activation.symbol] == "BUY_OPPORTUNITY"
    clock[0] += 5000
    await runtime.tick()
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_runtime_config_change_discards_old_round(env):
    adapter, client, clock, config, *_ = env
    await setup_activation(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    clock[0] += HOUR
    await runtime.tick()
    config["dry_run"] = True
    clock[0] += 5000
    await runtime.tick()
    assert not client.calls and runtime.status["BTC/USDC"] == "WAIT_ACCOUNT"
    assert not await model.PlacementIntent.exists()


@pytest.mark.asyncio
async def test_runtime_startup_rejects_never_submitted_buy_without_replaying_it(env):
    adapter, client, *_ = env
    buy_id = await prepared(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    await runtime.tick()
    assert (await model.PlacementIntent.get(operation_id=buy_id)).state == "rejected"
    assert not client.calls


@pytest.mark.asyncio
async def test_wallet_rebinding_evidence_uses_new_credentials_without_adopting_inventory(
    env,
):
    adapter, client, clock, *_ = env
    client.balance["free"]["BTC"] = "10.000000000000000001"
    evidence = await adapter.account_inventory("BTC/USDC", adapter.config())
    assert evidence.account_scope == accumulation_account_scope(adapter.config())
    assert evidence.free_base == "10.000000000000000001"
    assert evidence.observed_at_ms == clock[0]
    assert not client.calls and not await model.OpenTrades.exists()
    client.balance["timestamp"] = clock[0] - 10001
    with pytest.raises(AccumulationStateError, match="stale"):
        await adapter.account_inventory("BTC/USDC", adapter.config())
    client.balance.pop("timestamp")
    client.open_orders = [{"symbol": "BTC/USDC", "id": "external"}]
    with pytest.raises(AccumulationStateError, match="Open orders"):
        await adapter.account_inventory("BTC/USDC", adapter.config())


@pytest.mark.asyncio
async def test_settled_holding_can_rebind_after_restart_with_a_rotated_key(
    env, monkeypatch
):
    from service.accumulation_status import get_accumulation_status

    adapter, client, clock, config, *_ = env
    operation_id = await prepared(env)
    await AccumulationBuyExecutor(adapter).execute(operation_id)
    placement = await model.PlacementIntent.get(operation_id=operation_id)
    assert placement.state == "completed"
    original_order = json.loads(placement.result_json)
    holding = await model.OpenTrades.get(symbol="BTC/USDC")
    original_scope = (
        await model.AccumulationActivation.get(symbol=holding.symbol)
    ).account_scope
    client.balance["free"]["BTC"] = holding.accumulation_net_quantity
    config["key"] = "rotated-test-only-key"
    monkeypatch.setattr(
        adapter.exchange,
        "lookup_spot_order",
        AsyncMock(
            return_value=ExchangeOrderLookupResult(
                ExchangeOrderLookupStatus.FOUND, original_order
            )
        ),
    )
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup() and runtime.ready
    status = await get_accumulation_status(
        holding.symbol,
        wait_reasons={},
        configured_account_scope=runtime.current_account_scope,
    )
    assert status["account_matches"] is False
    result = await runtime.repairs.submit(
        {
            "symbol": holding.symbol,
            "action": "rebind_account",
            "operation_id": "after-key-rotation",
            "expected_revision": status["revision"],
        }
    )
    assert result.status == "applied" and result.state == "paused"
    activation = await model.AccumulationActivation.get(symbol=holding.symbol)
    assert activation.account_scope != original_scope
    assert activation.account_scope == runtime.current_account_scope
    assert activation.explicitly_paused
    await runtime.tick()
    assert len(client.calls) == 1  # Only the original simulated buy, no repair order.
    assert (
        await model.OpenTrades.get(id=holding.id)
    ).accumulation_net_quantity == holding.accumulation_net_quantity


@pytest.mark.asyncio
@pytest.mark.parametrize("quarantined", [False, True])
async def test_runtime_unknown_startup_order_blocks_readiness(
    env, monkeypatch, quarantined
):
    adapter, client, *_ = env
    buy_id = await prepared(env)
    client.failure = TimeoutError()
    await AccumulationBuyExecutor(adapter).execute(buy_id)
    if quarantined:
        await model.PlacementIntent.filter(operation_id=buy_id).update(
            state="restored_quarantined"
        )
    lookup = AsyncMock(
        return_value=ExchangeOrderLookupResult(ExchangeOrderLookupStatus.NOT_FOUND)
    )
    monkeypatch.setattr(adapter.exchange, "lookup_spot_order", lookup)
    runtime = AccumulationRuntime(adapter)
    assert not await runtime.startup()
    with pytest.raises(RuntimeError, match="not ready"):
        await runtime.run()
    assert len(client.calls) == 1
    assert bool(lookup.called) is not quarantined


@pytest.mark.asyncio
async def test_restored_quarantine_has_lookup_only_http_repair_access(env, monkeypatch):
    from types import SimpleNamespace

    import app as app_module
    from controller import accumulation as controller
    from httpx import ASGITransport, AsyncClient
    from litestar import Litestar, get, post, put
    from litestar.middleware import DefineMiddleware

    adapter, client, *_ = env
    buy_id = await prepared(env)
    client.failure = TimeoutError()
    await AccumulationBuyExecutor(adapter).execute(buy_id)
    placement = await model.PlacementIntent.get(operation_id=buy_id)
    placement.state = "restored_quarantined"
    await placement.save()
    activation = await model.AccumulationActivation.get(symbol="BTC/USDC")
    activation.state, activation.explicitly_paused = "paused", True
    await activation.save()
    lookup = AsyncMock(
        return_value=ExchangeOrderLookupResult(
            ExchangeOrderLookupStatus.FOUND,
            {
                "id": "recovered-zero-fill",
                "clientOrderId": placement.client_order_id,
                "symbol": "BTC/USDC",
                "side": "buy",
                "status": "canceled",
                "filled": "0",
                "cost": "0",
                "timestamp": NOW,
                "fees": [],
            },
        )
    )
    monkeypatch.setattr(adapter.exchange, "lookup_spot_order", lookup)
    runtime = AccumulationRuntime(adapter)
    monkeypatch.setattr(
        controller.accumulation_runtime, "ACCUMULATION_RUNTIME_AVAILABLE", True
    )
    monkeypatch.setattr(controller, "get_active_accumulation_runtime", lambda: runtime)

    async def context(func, *args, **kwargs):
        return await func(*args, **kwargs)

    config = SimpleNamespace(snapshot=lambda: env[3])
    db = SimpleNamespace(init=AsyncMock(), run_with_context=context)
    orders = SimpleNamespace(
        reconcile_placement_intents=AsyncMock(
            return_value=SimpleNamespace(ready=False, action_required=(buy_id,))
        )
    )
    services = SimpleNamespace(accumulation=runtime)
    monkeypatch.setattr(app_module, "runtime_state", app_module.RuntimeState())
    monkeypatch.setattr(app_module, "Database", lambda: db)
    monkeypatch.setattr(
        app_module, "Config", SimpleNamespace(instance=AsyncMock(return_value=config))
    )
    monkeypatch.setattr(app_module, "Orders", lambda: orders)
    monkeypatch.setattr(
        app_module, "build_accumulation_runtime", lambda provider: runtime
    )
    monkeypatch.setattr(app_module, "build_runtime_services", lambda **kwargs: services)
    monkeypatch.setattr(app_module, "activate_runtime_services", lambda graph: None)
    monkeypatch.setattr(app_module, "start_redis", lambda: None)
    monkeypatch.setattr(
        app_module, "coin_market_cap_rank_service", SimpleNamespace(start=AsyncMock())
    )
    cleanup = AsyncMock()
    monkeypatch.setattr(app_module, "shutdown", cleanup)
    start_ai = AsyncMock()
    monkeypatch.setattr(
        app_module, "ai_provider_client", SimpleNamespace(start=start_ai)
    )
    blocked_calls = []

    @post(path=["/orders/sell", "/config/live/activate", "/accumulation/activations"])
    async def forbidden_sale() -> dict[str, bool]:
        blocked_calls.append("sell")
        return {"sold": True}

    @put(path="/config/all")
    async def forbidden_config() -> dict[str, bool]:
        blocked_calls.append("config")
        return {"saved": True}

    @get(path="/trades/open")
    async def forbidden_history() -> dict[str, bool]:
        blocked_calls.append("history")
        return {"read": True}

    app = Litestar(
        route_handlers=[
            *controller.route_handlers,
            forbidden_sale,
            forbidden_config,
            forbidden_history,
        ],
        middleware=[DefineMiddleware(app_module.AccumulationRepairOnlyMiddleware)],
        openapi_config=None,
    )
    async with (
        app_module.runtime_lifespan(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost"
        ) as http,
    ):
        assert runtime.repair_ready and not runtime.ready
        assert app_module.runtime_state.watcher is None
        assert app_module.runtime_state.signal_plugin is None
        assert app_module.runtime_state.background_tasks == []
        start_ai.assert_not_awaited()
        current = await http.get("/accumulation/activation?symbol=BTC/USDC")
        assert current.status_code == 200
        payload = dict(
            symbol="BTC/USDC",
            action="repair_order",
            operation_id="http-restored-repair",
            expected_revision=current.json()["revision"],
            placement_operation_id=buy_id,
        )
        result = await http.post("/accumulation/repair", json=payload)
        assert (
            result.status_code == 200
            and result.json()["operation"]["status"] == "applied"
        )
        assert (
            await http.post("/accumulation/repair", json=payload)
        ).json() == result.json()
        assert (
            await http.post(
                "/accumulation/commands", json={**payload, "action": "resume"}
            )
        ).status_code == 409
        for method, path in (
            ("POST", "/orders/sell"),
            ("PUT", "/config/all"),
            ("POST", "/config/live/activate"),
            ("POST", "/accumulation/activations"),
            ("GET", "/trades/open"),
        ):
            rejected = await http.request(method, path, json={})
            assert rejected.status_code == (503 if method == "GET" else 409)
            assert rejected.json()["code"] == "recovery_only"
        assert blocked_calls == []
        downstream = AsyncMock()
        sent = AsyncMock()
        await app_module.AccumulationRepairOnlyMiddleware(downstream)(
            {"type": "websocket", "path": "/trades/ws"}, AsyncMock(), sent
        )
        sent.assert_awaited_once_with({"type": "websocket.close", "code": 1013})
        downstream.assert_not_awaited()
        assert (
            await http.post(
                "/accumulation/repair", json={**payload, "action": "adjust_inventory"}
            )
        ).status_code == 409
    cleanup.assert_awaited_once()
    await runtime.tick()
    assert not runtime.ready and len(client.calls) == 1
    lookup.assert_awaited_once()
    with pytest.raises(RuntimeError, match="not ready"):
        await runtime.run()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["not_paused", "unknown_acceptance", "mixed_dca"])
async def test_recovery_access_does_not_bypass_other_startup_gates(env, case):
    adapter, client, *_ = env
    buy_id = await prepared(env)
    client.failure = TimeoutError()
    await AccumulationBuyExecutor(adapter).execute(buy_id)
    await model.PlacementIntent.filter(operation_id=buy_id).update(
        state="restored_quarantined"
    )
    await model.AccumulationActivation.filter(symbol="BTC/USDC").update(
        state="paused", explicitly_paused=case != "not_paused"
    )
    if case == "unknown_acceptance":
        await model.PlacementIntent.filter(operation_id=buy_id).update(state="accepted")
        adapter.exchange.lookup_spot_order = AsyncMock(
            return_value=ExchangeOrderLookupResult(ExchangeOrderLookupStatus.NOT_FOUND)
        )
    if case == "mixed_dca":
        await model.PlacementIntent.create(
            operation_id="classic-unknown",
            symbol="ETH/USDC",
            exchange_name="binance",
            side="buy",
            action="buy",
            order_type="market",
            state="quarantined",
            request_json="{}",
        )
    runtime = AccumulationRuntime(adapter)
    assert not await runtime.startup()
    assert not runtime.ready and not runtime.repair_ready
    await runtime.tick()
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_runtime_expiry_cancels_owned_buy_but_waits_for_terminal_accounting(
    env, monkeypatch
):
    adapter, client, clock, *_ = env
    activation, _ = await setup_activation(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    clock[0] += HOUR
    await runtime.tick()
    report = {
        "id": "runtime-open",
        "symbol": activation.symbol,
        "side": "buy",
        "status": "open",
        "filled": "0",
        "cost": "0",
        "timestamp": clock[0],
    }
    client.response = report
    clock[0] += 5000
    await runtime.tick()
    placement = await model.PlacementIntent.get(side="buy")

    async def lookup(*args, **kwargs):
        return ExchangeOrderLookupResult(
            ExchangeOrderLookupStatus.FOUND, copy.deepcopy(report)
        )

    cancel = AsyncMock(return_value={"status": "canceled"})
    monkeypatch.setattr(adapter.exchange, "lookup_spot_order", lookup)
    monkeypatch.setattr(adapter.exchange, "cancel_spot_order", cancel)
    clock[0] += HOUR
    await runtime.tick()
    assert cancel.call_count == 1
    await placement.refresh_from_db()
    assert placement.state == "accepted"
    opportunity = await model.AccumulationOpportunity.get(unresolved_slot=activation.id)
    assert opportunity.consumed_at is None
    report.update(
        status="canceled",
        filled="1",
        cost="60",
        fees=[{"currency": "USDC", "cost": "0"}],
    )
    client.balance["free"]["BTC"] = "1"
    clock[0] += 5000
    await runtime.tick()
    await placement.refresh_from_db()
    await opportunity.refresh_from_db()
    assert placement.state == "completed" and opportunity.unresolved_slot is None
    assert opportunity.consumed_at is not None
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_runtime_executes_persisted_close_command_but_never_replaces_sale(env):
    adapter, client, *_ = env
    activation, _ = await manual_sale(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    await runtime.tick()
    await activation.refresh_from_db()
    assert activation.state == "stopped" and len(client.calls) == 2
    runtime.notify(activation.symbol)
    await runtime.tick()
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_runtime_rebase_cannot_override_pause_or_clear_consumption(
    env, monkeypatch
):
    adapter, client, *_ = env
    buy_id = await prepared(env)
    await AccumulationBuyExecutor(adapter).execute(buy_id)
    activation = await model.AccumulationActivation.get(symbol="BTC/USDC")
    holding = await model.OpenTrades.get(id=activation.holding_id)
    client.balance["free"]["BTC"] = holding.accumulation_net_quantity
    guard = activation.execution_guard_json
    original = adapter.readiness

    async def paused(request):
        ready = await original(request)
        await AccumulationLifecycleService().submit(
            dict(
                symbol=activation.symbol,
                action="pause",
                operation_id="pause-rebase",
                expected_revision=activation.revision,
            ),
            account_scope=activation.account_scope,
        )
        return ready

    service = AccumulationLifecycleService(paused)
    with pytest.raises(AccumulationStateError, match="changed"):
        await service.rebase_enabled(
            str(activation.id), account_scope=activation.account_scope
        )
    await activation.refresh_from_db()
    assert activation.state == "paused" and activation.execution_guard_json == guard
    assert activation.consumption_revision == 1


@pytest.mark.asyncio
async def test_runtime_gap_rebases_without_historical_purchase(env):
    adapter, client, clock, *_ = env
    activation, _ = await setup_activation(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    clock[0] += 5 * HOUR
    await runtime.tick()
    await activation.refresh_from_db()
    assert activation.baseline_close_ms == 605 * HOUR
    assert activation.observation_epoch == 2
    assert not client.calls and not await model.AccumulationOpportunity.exists()


@pytest.mark.asyncio
async def test_runtime_maintenance_defers_work_without_losing_notifications(env):
    adapter, client, clock, _, _, barrier = env
    activation, _ = await setup_activation(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    clock[0] += HOUR
    runtime.notify(activation.symbol)
    async with barrier.maintenance():
        await runtime.tick()
        assert not await model.AccumulationOpportunity.exists()
    await runtime.tick()
    assert await model.AccumulationOpportunity.exists()
    assert not client.calls


@pytest.mark.asyncio
async def test_runtime_shutdown_during_submission_preserves_lookup_identity(env):
    adapter, client, clock, *_ = env
    await setup_activation(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    clock[0] += HOUR
    await runtime.tick()
    clock[0] += 5000
    entered = asyncio.Event()

    async def stalled():
        entered.set()
        await asyncio.Event().wait()

    client.on_submit = stalled
    task = asyncio.create_task(runtime.run())
    await asyncio.wait_for(entered.wait(), timeout=2)
    runtime.request_stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await runtime.shutdown()
    row = await model.PlacementIntent.get(side="buy")
    assert row.state == "submitting" and row.client_order_id
    assert await model.AccumulationOpportunity.filter(
        unresolved_slot__isnull=False
    ).exists()
    await runtime.tick()
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_runtime_unexpected_database_failure_reaches_task_supervision(
    env, monkeypatch
):
    adapter, *_ = env
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    monkeypatch.setattr(
        model.AccumulationActivation,
        "all",
        lambda: (_ for _ in ()).throw(OperationalError("database unavailable")),
    )
    with pytest.raises(OperationalError):
        await runtime.run()


@pytest.mark.asyncio
async def test_runtime_restart_rebase_preserves_filled_opportunity_guard(env):
    adapter, client, *_ = env
    buy_id = await prepared(env)
    await AccumulationBuyExecutor(adapter).execute(buy_id)
    activation = await model.AccumulationActivation.get(symbol="BTC/USDC")
    holding = await model.OpenTrades.get(id=activation.holding_id)
    client.balance["free"]["BTC"] = holding.accumulation_net_quantity
    guard, consumption = (
        activation.execution_guard_json,
        activation.consumption_revision,
    )
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    await runtime.tick()
    await activation.refresh_from_db()
    assert activation.execution_guard_json == guard
    assert activation.consumption_revision == consumption
    assert len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["completed", "rejected"])
async def test_runtime_retry_timer_only_requeues_terminal_exchange_zero_fill(
    env, terminal
):
    from datetime import datetime, timezone

    adapter, _, clock, *_ = env
    buy_id = await prepared(env)
    placement = await model.PlacementIntent.get(operation_id=buy_id)
    attempt = await model.AccumulationAttempt.get(placement=placement)
    opportunity = await model.AccumulationOpportunity.get(id=attempt.opportunity_id)
    placement.state = terminal
    await placement.save()
    opportunity.status = "retryable"
    opportunity.next_retry_at = datetime.fromtimestamp(
        (clock[0] + 1000) / 1000, timezone.utc
    )
    await opportunity.save()
    runtime = AccumulationRuntime(adapter)
    assert not await runtime._retry_due(clock[0])
    clock[0] += 1000
    assert await runtime._retry_due(clock[0]) == (
        {"BTC/USDC"} if terminal == "completed" else set()
    )
    assert not await runtime._retry_due(clock[0])


async def _entry_service(env, monkeypatch, *, signal="csv_signal"):
    from service import signal_runtime
    from service.accumulation_entry import AccumulationEntryService

    adapter, _, _, config, *_ = env
    version = await model.StrategyVersion.create(
        strategy_slug="accumulation_dip_v1",
        version=1,
        ir_json=json.dumps(build_accumulation_strategy_document()),
        validation_json="{}",
        explanation="experimental",
    )
    config.update(
        trade_mode="accumulation",
        signal=signal,
        bo=25,
        max_bots=3,
        accumulation_strategy_version_id=version.id,
        symbol_list="BTC/USDC",
    )
    monkeypatch.setattr(signal_runtime, "_PENDING_ADMISSION_LOCK", asyncio.Lock())
    monkeypatch.setattr(signal_runtime, "_PENDING_ADMISSION_SYMBOLS", set())
    notified = []
    return AccumulationEntryService(adapter, notified.append), notified


ENTRY_CSV = "date;symbol;price;amount\n1970-01-02;BTC/USDC;60.000000000000000001;0.100000000000000001"


async def _staged_payload(
    previous, action="retry_entry", operation_id="entry-retry", **extra
):
    activation = await model.AccumulationActivation.get(symbol="BTC/USDC")
    return dict(
        symbol=activation.symbol,
        action=action,
        operation_id=operation_id,
        expected_revision=activation.revision,
        previous_operation_id=previous.operation_id,
        **extra,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("currency", ["USDC", "usdc"])
async def test_csv_entry_adopts_exact_owned_inventory_without_fabricating_fills(
    env, monkeypatch, currency
):
    env[3]["currency"] = currency
    service, notified = await _entry_service(env, monkeypatch)
    _, client, *_ = env
    client.balance["free"]["BTC"] = "2"
    result = (await service.csv(ENTRY_CSV))[0]
    assert result.reason == "ENABLED"
    holding = await model.OpenTrades.get()
    assert holding.accumulation_net_quantity == "0.100000000000000001"
    assert (
        holding.accumulation_remaining_cost == "6.000000000000000060100000000000000001"
    )
    assert holding.accumulation_contributed_quote == holding.accumulation_remaining_cost
    assert holding.accumulation_basis_provenance == "csv_declared_fees_unknown"
    assert json.loads(holding.accumulation_fees_json) == {
        "totals": {},
        "pending_reports": 1,
    }
    assert not holding.execution_history_complete
    assert await model.Trades.all().count() == 0
    assert await model.TradeExecutions.all().count() == 0
    assert await model.PlacementIntent.all().count() == 0
    assert not client.calls
    assert notified == ["BTC/USDC"]
    again = (await service.csv(ENTRY_CSV))[0]
    assert again.reason == "ALREADY_REGISTERED"
    assert await model.OpenTrades.all().count() == 1
    assert (await model.AccumulationActivation.get()).holding_id == holding.id


@pytest.mark.asyncio
async def test_csv_shortfall_stays_staged_until_explicit_retry(env, monkeypatch):
    service, notified = await _entry_service(env, monkeypatch)
    adapter, client, *_ = env
    adapter.read_inputs = AsyncMock(wraps=adapter.read_inputs)
    result = (await service.csv(ENTRY_CSV))[0]
    assert result.reason == "WAIT_VALIDATION"
    activation = await model.AccumulationActivation.get()
    assert activation.explicitly_paused and activation.state == "validating"
    assert await model.OpenTrades.all().count() == 0
    client.balance["free"]["BTC"] = "2"
    await service.csv(ENTRY_CSV)
    assert adapter.read_inputs.await_count == 1
    assert not notified
    retried = await service.submit_staged(await _staged_payload(result))
    assert retried.status == "applied" and retried.state == "enabled"
    assert await model.OpenTrades.all().count() == 1
    assert not client.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["ledger", "config", "time"])
async def test_csv_ownership_evidence_rechecked_at_commit(env, monkeypatch, change):
    service, _ = await _entry_service(env, monkeypatch)
    adapter, client, clock, config, *_ = env
    client.balance["free"]["BTC"] = "2"
    original = adapter.read_inputs

    async def read(*args, **kwargs):
        inputs = await original(*args, **kwargs)
        if change == "ledger":
            await model.OpenTrades.create(symbol="BTC/USDT", amount=2)
        elif change == "config":
            config["trading_paused"] = True
        else:
            clock[0] += 10001
        return inputs

    monkeypatch.setattr(adapter, "read_inputs", read)
    assert (await service.csv(ENTRY_CSV))[0].reason == "WAIT_VALIDATION"
    assert not await model.OpenTrades.filter(symbol="BTC/USDC").exists()
    assert (await model.AccumulationActivation.get()).explicitly_paused


@pytest.mark.asyncio
async def test_csv_owned_base_includes_other_managed_quote_pairs(env, monkeypatch):
    service, _ = await _entry_service(env, monkeypatch)
    _, client, *_ = env
    client.balance["free"]["BTC"] = "1.05"
    await model.OpenTrades.create(symbol="BTC/USDT", amount=1)
    assert (await service.csv(ENTRY_CSV))[0].reason == "WAIT_VALIDATION"
    assert not await model.OpenTrades.filter(symbol="BTC/USDC").exists()


@pytest.mark.asyncio
async def test_csv_rejects_changed_declaration_and_existing_classic_holding(
    env, monkeypatch
):
    service, _ = await _entry_service(env, monkeypatch)
    await service.csv(ENTRY_CSV)
    with pytest.raises(AccumulationStateError, match="correction"):
        await service.csv(ENTRY_CSV.replace("0.100000000000000001", "0.2"))
    # A different symbol already managed by DCA cannot be adopted by this mode.
    await model.OpenTrades.create(symbol="ETH/USDC", amount=1)
    with pytest.raises(AccumulationStateError, match="managed"):
        await service.csv(ENTRY_CSV.replace("BTC", "ETH"))


@pytest.mark.asyncio
@pytest.mark.parametrize("currency", ["USDC", "usdc"])
async def test_asap_registers_without_buy_and_counts_zero_inventory_slot(
    env, monkeypatch, currency
):
    env[3]["currency"] = currency
    from service.signal_runtime import get_active_open_symbols

    service, notified = await _entry_service(env, monkeypatch, signal="asap")
    _, client, _, config, *_ = env
    config.update(max_bots=1, symbol_list="BTC/USDC,ETH/USDC")
    results = await service.asap()
    assert [item.reason for item in results] == ["ENABLED", "WAIT_CAPACITY"]
    assert await get_active_open_symbols() == ["BTC/USDC"]
    assert not await model.OpenTrades.all().exists()
    assert not client.calls
    assert notified == ["BTC/USDC"]
    activation = await model.AccumulationActivation.get()
    activation.state = "stopped"
    activation.explicitly_paused = True
    await activation.save()
    config["symbol_list"] = "BTC/USDC"
    assert (await service.asap())[0].reason == "STOPPED"
    assert (
        await model.AccumulationActivation.get()
    ).generation == activation.generation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol_list", "https://example.test/pairs"),
        ("symbol_list", "BTC/USDT"),
        ("signal", "sym_signals"),
        ("trading_paused", True),
        ("accumulation_strategy_version_id", None),
    ],
)
async def test_asap_entry_rejects_unsupported_setup_before_staging(
    env, monkeypatch, field, value
):
    service, _ = await _entry_service(env, monkeypatch, signal="asap")
    env[3][field] = value
    with pytest.raises(AccumulationStateError):
        await service.asap()
    assert not await model.AccumulationActivation.all().exists()


@pytest.mark.parametrize(
    "row",
    [
        "1970-01-02;BTC/USDC;NaN;1",
        "1970-01-02;BTC/USDC;1;Infinity",
        "1970-01-02;BTC/USDC;0;1",
        "1970-01-02;BTC/USDC;1;-1",
        "2099-01-02;BTC/USDC;1;1",
        "1970-01-02;BTC/USDT;1;1",
        "1970-01-02;BTC/USDC;1;1\n1970-01-02;BTC/USDC;1;1",
    ],
)
def test_accumulation_csv_rejects_invalid_declarations(row):
    from service.accumulation_import import parse_accumulation_csv

    with pytest.raises(ValueError):
        parse_accumulation_csv(row, "USDC", now_ms=NOW)


@pytest.mark.asyncio
async def test_concurrent_csv_entry_has_one_inventory_and_declaration(env, monkeypatch):
    service, _ = await _entry_service(env, monkeypatch)
    env[1].balance["free"]["BTC"] = "2"
    results = await asyncio.gather(service.csv(ENTRY_CSV), service.csv(ENTRY_CSV))
    assert sorted(batch[0].reason for batch in results) == [
        "ALREADY_REGISTERED",
        "ENABLED",
    ]
    assert await model.OpenTrades.all().count() == 1
    assert await model.AccumulationLifecycleOperation.all().count() == 1


@pytest.mark.asyncio
async def test_csv_external_order_does_not_adopt_or_cancel(env, monkeypatch):
    service, _ = await _entry_service(env, monkeypatch)
    client = env[1]
    client.balance["free"]["BTC"] = "2"
    client.open_orders = [
        {"id": "external", "symbol": "BTC/USDC", "side": "sell", "remaining": "1"}
    ]
    assert (await service.csv(ENTRY_CSV))[0].reason == "WAIT_VALIDATION"
    assert not await model.OpenTrades.all().exists()
    assert not client.calls


@pytest.mark.asyncio
async def test_csv_restart_does_not_reimport_or_enable_staged_inventory(
    env, monkeypatch
):
    from service.accumulation_entry import AccumulationEntryService

    service, _ = await _entry_service(env, monkeypatch)
    adapter, client, _, _, url, *_ = env
    first = (await service.csv(ENTRY_CSV))[0]
    await Tortoise.close_connections()
    await Tortoise.init(db_url=url, modules={"models": ["model"]})
    client.balance["free"]["BTC"] = "2"
    restarted = AccumulationEntryService(adapter, lambda _: None)
    second = (await restarted.csv(ENTRY_CSV))[0]
    assert second.operation_id == first.operation_id
    assert second.reason == "ALREADY_REGISTERED"
    assert not await model.OpenTrades.all().exists()
    assert (await model.AccumulationActivation.get()).explicitly_paused


@pytest.mark.asyncio
async def test_legacy_csv_cannot_adopt_a_stopped_accumulation_symbol(env):
    from service.csv_signal_import import CSVSignalImportService

    activation, _ = await setup_activation(env)
    activation.state = "stopped"
    activation.explicitly_paused = True
    await activation.save()
    with pytest.raises(ValueError, match="reserved"):
        await CSVSignalImportService().import_from_csv(ENTRY_CSV, "USDC", 1.0)
    assert not await model.OpenTrades.all().exists()
    assert not await model.Trades.all().exists()


@pytest.mark.asyncio
async def test_entry_config_change_after_staging_cannot_enable_symbol(env, monkeypatch):
    service, _ = await _entry_service(env, monkeypatch, signal="asap")
    original = service.lifecycle.stage_activation

    async def stage(**kwargs):
        result = await original(**kwargs)
        env[3]["trading_paused"] = True
        return result

    monkeypatch.setattr(service.lifecycle, "stage_activation", stage)
    assert (await service.asap())[0].reason == "WAIT_VALIDATION"
    assert (await model.AccumulationActivation.get()).state == "validating"
    assert not env[1].calls


@pytest.mark.asyncio
async def test_csv_activation_missing_persisted_declaration_cannot_enable(
    env, monkeypatch
):
    service, _ = await _entry_service(env, monkeypatch)
    result = (await service.csv(ENTRY_CSV))[0]
    operation = await model.AccumulationLifecycleOperation.get(
        operation_id=result.operation_id
    )
    payload = json.loads(operation.request_json)
    del payload["imported_inventory"]
    operation.request_json = json.dumps(payload)
    await operation.save()
    with pytest.raises(AccumulationStateError, match="missing its inventory"):
        await service.submit_staged(await _staged_payload(result))
    assert (await model.AccumulationActivation.get()).explicitly_paused
    assert not await model.OpenTrades.all().exists()


@pytest.mark.asyncio
async def test_staged_correction_preserves_history_and_requires_explicit_retry(
    env, monkeypatch
):
    service, notified = await _entry_service(env, monkeypatch)
    adapter, client, *_ = env
    initial = (await service.csv(ENTRY_CSV))[0]
    original = await model.AccumulationLifecycleOperation.get(
        operation_id=initial.operation_id
    )
    client.balance["free"]["BTC"] = "2"
    adapter.readiness = AsyncMock(wraps=adapter.readiness)
    corrected_csv = ENTRY_CSV.replace("0.100000000000000001", "0.2")
    payload = await _staged_payload(
        initial, "correct_import", "entry-correction", csv_content=corrected_csv
    )
    corrected = await service.submit_staged(payload)
    assert corrected.status == "pending" and corrected.state == "validating"
    assert await service.submit_staged(payload) == corrected
    adapter.readiness.assert_not_awaited()
    assert not await model.OpenTrades.all().exists()
    await original.refresh_from_db()
    assert original.status == "continued"
    assert (
        json.loads(original.request_json)["imported_inventory"]["quantity"]
        == "0.100000000000000001"
    )
    assert (await service.csv(ENTRY_CSV))[0].reason == "ALREADY_REGISTERED"
    with pytest.raises(AccumulationStateError, match="explicit staged correction"):
        await service.csv(corrected_csv)
    retry_payload = await _staged_payload(corrected)
    result = await service.submit_staged(retry_payload)
    assert result.state == "enabled" and result.status == "applied"
    assert await service.submit_staged(retry_payload) == result
    assert adapter.readiness.await_count == 1
    assert (await model.OpenTrades.get()).accumulation_net_quantity == "0.2"
    assert (
        await model.AccumulationActivation.get()
    ).strategy_version_id == original.target_version_id
    assert not client.calls and notified and set(notified) == {"BTC/USDC"}
    assert not await model.TradeExecutions.all().exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["retry_entry", "correct_import", "abandon_entry"])
async def test_staged_commands_reject_stale_revision_and_changed_idempotent_payload(
    env, monkeypatch, action
):
    service, _ = await _entry_service(env, monkeypatch)
    initial = (await service.csv(ENTRY_CSV))[0]
    extra = {"csv_content": ENTRY_CSV} if action == "correct_import" else {}
    payload = await _staged_payload(initial, action, "entry-command", **extra)
    result = await service.submit_staged(payload)
    assert await service.submit_staged(payload) == result
    with pytest.raises(AccumulationStateError, match="different request"):
        await service.submit_staged(
            {**payload, "expected_revision": payload["expected_revision"] + 1}
        )
    with pytest.raises(AccumulationStateError, match="Stale lifecycle"):
        await service.submit_staged({**payload, "operation_id": "stale-client"})


@pytest.mark.asyncio
async def test_abandon_staged_entry_retains_registry_and_never_sells(env, monkeypatch):
    service, _ = await _entry_service(env, monkeypatch)
    initial = (await service.csv(ENTRY_CSV))[0]
    result = await service.submit_staged(
        await _staged_payload(initial, "abandon_entry")
    )
    assert result.state == "stopped" and result.status == "applied"
    assert (await service.csv(ENTRY_CSV))[0].reason == "STOPPED"
    assert not await model.OpenTrades.all().exists()
    assert not await model.PlacementIntent.all().exists()
    assert not env[1].calls
    with pytest.raises(AccumulationStateError, match="current staged declaration"):
        await service.submit_staged(
            await _staged_payload(initial, operation_id="late-retry")
        )
    with pytest.raises(AccumulationStateError, match="staged-entry controls"):
        await service.lifecycle.submit(
            dict(
                symbol="BTC/USDC",
                action="reactivate",
                operation_id="wrong-reactivate",
                expected_revision=result.revision,
            ),
            account_scope=accumulation_account_scope(env[3]),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["resume", "switch_strategy"])
async def test_paused_unadopted_csv_cannot_bypass_import_but_can_retry(
    env, monkeypatch, action
):
    service, _ = await _entry_service(env, monkeypatch)
    initial = (await service.csv(ENTRY_CSV))[0]
    activation = await model.AccumulationActivation.get()
    scope = accumulation_account_scope(env[3])
    paused = await service.lifecycle.submit(
        dict(
            symbol=activation.symbol,
            action="pause",
            operation_id="pause-entry",
            expected_revision=activation.revision,
        ),
        account_scope=scope,
    )
    extra = (
        {"target_version_id": activation.strategy_version_id}
        if action == "switch_strategy"
        else {}
    )
    with pytest.raises(AccumulationStateError, match="staged-entry controls"):
        await service.lifecycle.submit(
            dict(
                symbol=activation.symbol,
                action=action,
                operation_id="bypass",
                expected_revision=paused.revision,
                **extra,
            ),
            account_scope=scope,
        )
    env[1].balance["free"]["BTC"] = "2"
    result = await service.submit_staged(await _staged_payload(initial))
    assert result.state == "enabled"
    assert (
        await model.OpenTrades.get()
    ).accumulation_net_quantity == "0.100000000000000001"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["activate", "retry_entry", "correct_import"])
async def test_runtime_cannot_automatically_validate_staged_entries(
    env, monkeypatch, action
):
    service, _ = await _entry_service(env, monkeypatch)
    initial = (await service.csv(ENTRY_CSV))[0]
    if action != "activate":
        extra = {"csv_content": ENTRY_CSV} if action == "correct_import" else {}
        initial = await service.submit_staged(
            await _staged_payload(initial, action, **extra)
        )
    env[1].balance["free"]["BTC"] = "2"
    env[0].readiness = AsyncMock(wraps=env[0].readiness)
    runtime = AccumulationRuntime(env[0])
    assert await runtime.startup()
    await runtime.tick()
    runtime.notify("BTC/USDC")
    await runtime.tick()
    assert runtime.status["BTC/USDC"] == "WAIT_ENTRY_VALIDATION"
    env[0].readiness.assert_not_awaited()
    assert not await model.OpenTrades.all().exists()
    assert not env[1].calls


@pytest.mark.asyncio
async def test_staged_correction_wins_race_with_validation_before_adoption(
    env, monkeypatch
):
    service, _ = await _entry_service(env, monkeypatch)
    initial = (await service.csv(ENTRY_CSV))[0]
    env[1].balance["free"]["BTC"] = "2"
    entered, release = asyncio.Event(), asyncio.Event()
    readiness = env[0].readiness

    async def delayed(request):
        result = await readiness(request)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(env[0], "readiness", delayed)
    retry = asyncio.create_task(service.submit_staged(await _staged_payload(initial)))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        pending = await model.AccumulationLifecycleOperation.get(
            operation_id="entry-retry"
        )
        correction = await service.submit_staged(
            await _staged_payload(
                pending,
                "correct_import",
                "race-correction",
                csv_content=ENTRY_CSV.replace("0.100000000000000001", "0.2"),
            )
        )
    finally:
        release.set()
    result = await retry
    assert result.status == "continued"
    assert (await model.AccumulationActivation.get()).revision == correction.revision
    assert not await model.OpenTrades.all().exists()


@pytest.mark.asyncio
async def test_staged_command_journal_failure_rolls_back_predecessor_and_activation(
    env, monkeypatch
):
    service, _ = await _entry_service(env, monkeypatch)
    initial = (await service.csv(ENTRY_CSV))[0]
    payload = await _staged_payload(initial, "abandon_entry")
    monkeypatch.setattr(
        model.AccumulationLifecycleOperation,
        "create",
        AsyncMock(side_effect=RuntimeError("disk failure")),
    )
    with pytest.raises(RuntimeError, match="disk failure"):
        await service.submit_staged(payload)
    activation = await model.AccumulationActivation.get()
    assert (
        activation.revision == payload["expected_revision"]
        and activation.state == "validating"
    )
    assert (await model.AccumulationLifecycleOperation.get()).status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["correct_import", "abandon_entry", "retry_entry"])
async def test_staged_commands_cannot_modify_adopted_inventory(
    env, monkeypatch, action
):
    service, _ = await _entry_service(env, monkeypatch)
    env[1].balance["free"]["BTC"] = "2"
    initial = (await service.csv(ENTRY_CSV))[0]
    extra = {"csv_content": ENTRY_CSV} if action == "correct_import" else {}
    with pytest.raises(AccumulationStateError, match="unadopted"):
        await service.submit_staged(await _staged_payload(initial, action, **extra))
    assert (
        await model.OpenTrades.get()
    ).accumulation_net_quantity == "0.100000000000000001"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"expected_revision": True},
        {"expected_revision": -1},
        {"action": []},
        {"symbol": None},
        {"operation_id": "has spaces"},
        {"account_scope": "client-supplied"},
        {"csv_content": "unexpected"},
    ],
)
async def test_invalid_staged_requests_have_no_database_or_exchange_effects(
    env, monkeypatch, change
):
    service, _ = await _entry_service(env, monkeypatch)
    initial = (await service.csv(ENTRY_CSV))[0]
    payload = await _staged_payload(initial)
    env[0].readiness = AsyncMock(wraps=env[0].readiness)
    with pytest.raises((AccumulationStateError, ValueError)):
        await service.submit_staged({**payload, **change})
    env[0].readiness.assert_not_awaited()
    assert await model.AccumulationLifecycleOperation.all().count() == 1
    assert (await model.AccumulationActivation.get()).revision == payload[
        "expected_revision"
    ]


@pytest.mark.asyncio
async def test_competing_staged_dashboard_commands_only_accept_one_revision(
    env, monkeypatch
):
    service, _ = await _entry_service(env, monkeypatch)
    initial = (await service.csv(ENTRY_CSV))[0]
    first = await _staged_payload(
        initial, "correct_import", "dashboard-one", csv_content=ENTRY_CSV
    )
    second = await _staged_payload(initial, "abandon_entry", "dashboard-two")
    results = await asyncio.gather(
        service.submit_staged(first),
        service.submit_staged(second),
        return_exceptions=True,
    )
    assert sum(isinstance(result, AccumulationStateError) for result in results) == 1
    assert await model.AccumulationLifecycleOperation.all().count() == 2
    assert (await model.AccumulationActivation.get()).revision == first[
        "expected_revision"
    ] + 1


@pytest.mark.asyncio
async def test_staged_retry_is_bound_to_predecessor_account_and_execution_uncertainty(
    env, monkeypatch
):
    service, _ = await _entry_service(env, monkeypatch)
    initial = (await service.csv(ENTRY_CSV))[0]
    payload = await _staged_payload(initial)
    with pytest.raises(AccumulationStateError, match="current staged"):
        await service.submit_staged({**payload, "previous_operation_id": "wrong-entry"})
    env[3]["key"] = "another-test-account"
    with pytest.raises(AccumulationStateError, match="account scope changed"):
        await service.submit_staged(payload)
    env[3]["key"] = CONFIG["key"]
    await model.PlacementIntent.create(
        operation_id="unresolved",
        exchange_name="binance",
        action="accumulation_buy",
        symbol="BTC/USDC",
        side="buy",
        order_type="limit",
        requested_amount=1,
        state="restored_quarantined",
        client_order_id="unknown-owned-order",
    )
    with pytest.raises(AccumulationStateError, match="reconciliation"):
        await service.submit_staged(payload)
    assert await model.AccumulationLifecycleOperation.all().count() == 1


@pytest.mark.asyncio
async def test_http_close_journals_once_and_only_runtime_submits_sale(env, monkeypatch):
    from controller import accumulation as controller
    from httpx import ASGITransport, AsyncClient
    from litestar import Litestar

    service, _ = await _entry_service(env, monkeypatch)
    adapter, client, *_ = env
    client.balance["free"]["BTC"] = "2"
    await service.csv(ENTRY_CSV)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    monkeypatch.setattr(
        controller.accumulation_runtime, "ACCUMULATION_RUNTIME_AVAILABLE", True
    )
    monkeypatch.setattr(controller, "get_active_accumulation_runtime", lambda: runtime)
    app = Litestar(route_handlers=controller.route_handlers, openapi_config=None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost"
    ) as http:
        current = (await http.get("/accumulation/activation?symbol=BTC/USDC")).json()
        assert current["holding"]["fees"] == {"totals": {}, "pending_reports": 1}
        request = dict(
            symbol="BTC/USDC",
            action="close",
            expected_revision=current["revision"],
            operation_id="http-close",
        )
        first = await http.post("/accumulation/commands", json=request)
        assert first.status_code == 202
        assert (
            await http.post("/accumulation/commands", json=request)
        ).json() == first.json()
        assert not client.calls
        conflict = await http.post(
            "/accumulation/commands",
            json={**request, "operation_id": "stale-http-close"},
        )
        assert conflict.status_code == 409
        assert runtime._wake.is_set()
        await runtime.tick()
        assert len(client.calls) == 1 and client.calls[0][1:3] == ("market", "sell")
        final = (await http.get("/accumulation/activation?symbol=BTC/USDC")).json()
        assert final["state"] == "closing"  # Precision remainder remains managed.
        assert final["holding"]["net_quantity"] == "0.000000000000000001"
        assert (
            await http.post("/accumulation/commands", json=request)
        ).status_code == 202
        await runtime.tick()
        assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_http_staged_commands_use_snapshot_revision_and_explicit_validation(
    env, monkeypatch
):
    from controller import accumulation as controller
    from httpx import ASGITransport, AsyncClient
    from litestar import Litestar

    service, _ = await _entry_service(env, monkeypatch)
    initial = (await service.csv(ENTRY_CSV))[0]
    runtime = AccumulationRuntime(env[0])
    assert await runtime.startup()
    monkeypatch.setattr(
        controller.accumulation_runtime, "ACCUMULATION_RUNTIME_AVAILABLE", True
    )
    monkeypatch.setattr(controller, "get_active_accumulation_runtime", lambda: runtime)
    app = Litestar(route_handlers=controller.route_handlers, openapi_config=None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost"
    ) as http:
        snapshot = (await http.get("/accumulation/activation?symbol=BTC/USDC")).json()
        corrected = await http.post(
            "/accumulation/entry/commands",
            json=dict(
                symbol=snapshot["symbol"],
                action="correct_import",
                operation_id="http-correct",
                previous_operation_id=snapshot["entry"]["operation_id"],
                expected_revision=snapshot["revision"],
                csv_content=ENTRY_CSV.replace("0.100000000000000001", "0.2"),
            ),
        )
        assert corrected.status_code == 202
        env[1].balance["free"]["BTC"] = "2"
        await runtime.tick()
        assert not await model.OpenTrades.all().exists()
        snapshot = (await http.get("/accumulation/activation?symbol=BTC/USDC")).json()
        assert snapshot["entry"]["declaration"]["net_quantity"] == "0.2"
        retry = await http.post(
            "/accumulation/entry/commands",
            json=dict(
                symbol=snapshot["symbol"],
                action="retry_entry",
                operation_id="http-retry",
                previous_operation_id=snapshot["entry"]["operation_id"],
                expected_revision=snapshot["revision"],
            ),
        )
        assert (
            retry.status_code == 200 and retry.json()["operation"]["state"] == "enabled"
        )
        stale = await http.post(
            "/accumulation/entry/commands",
            json=await _staged_payload(initial, "abandon_entry"),
        )
        assert stale.status_code == 409
        assert (await model.OpenTrades.get()).accumulation_net_quantity == "0.2"
        assert not env[1].calls


@pytest.mark.asyncio
async def test_runtime_strategy_switch_retains_purchase_guard_and_pause(env):
    from service.accumulation_catalog import create_accumulation_strategy

    buy_id = await prepared(env)
    await AccumulationBuyExecutor(env[0]).execute(buy_id)
    activation = await model.AccumulationActivation.get()
    env[1].balance["free"]["BTC"] = (
        await model.OpenTrades.get(id=activation.holding_id)
    ).accumulation_net_quantity
    activation.state, activation.explicitly_paused = "paused", True
    await activation.save()
    guard, consumed, old_pin = (
        activation.execution_guard_json,
        activation.consumption_revision,
        activation.strategy_version_id,
    )
    parameters = build_accumulation_strategy_document()["parameters"]
    target = await create_accumulation_strategy(
        {
            "operation_id": "switch-variant",
            "name": "Patient dip",
            "parameters": {**parameters, "spacing_atr": "2"},
        }
    )
    runtime = AccumulationRuntime(env[0])
    assert await runtime.startup()
    result = await runtime.submit_command(
        dict(
            symbol=activation.symbol,
            action="switch_strategy",
            operation_id="operator-switch",
            expected_revision=activation.revision,
            target_version_id=target["id"],
        )
    )
    await activation.refresh_from_db()
    assert result.status == "pending" and activation.strategy_version_id == old_pin
    before = len(env[1].calls)
    await runtime.tick()
    await activation.refresh_from_db()
    assert activation.strategy_version_id == target["id"]
    assert activation.state == "paused" and activation.explicitly_paused
    assert (
        activation.execution_guard_json == guard
        and activation.consumption_revision == consumed
    )
    assert len(env[1].calls) == before


@pytest.mark.asyncio
async def test_runtime_rejects_dynamic_dca_version_before_journaling_switch(env):
    activation, _ = await setup_activation(env)
    ordinary = await model.StrategyVersion.create(
        strategy_slug="ordinary",
        version=1,
        ir_json='{"root":"decision","nodes":[]}',
        validation_json="{}",
        explanation="test",
    )
    runtime = AccumulationRuntime(env[0])
    assert await runtime.startup()
    await activation.refresh_from_db()
    revision = activation.revision
    with pytest.raises(AccumulationStateError, match="accumulation contract"):
        await runtime.submit_command(
            dict(
                symbol=activation.symbol,
                action="switch_strategy",
                operation_id="invalid-switch",
                expected_revision=revision,
                target_version_id=ordinary.id,
            )
        )
    await activation.refresh_from_db()
    assert activation.revision == revision and activation.state == "enabled"
    assert not await model.AccumulationLifecycleOperation.all().exists()


@pytest.mark.asyncio
async def test_incomplete_demo_draft_stays_available_without_exchange_actions(env):
    adapter, client, _, config, *_ = env
    config.update(dry_run=True, key="", secret="")
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup() and runtime.ready
    await runtime.tick()
    assert runtime.status["*"] == "WAIT_ACCOUNT" and not client.calls


@pytest.mark.asyncio
async def test_dynamic_dca_without_native_registry_never_validates_accumulation_credentials(
    env, monkeypatch
):
    adapter, client, _, config, *_ = env
    config.update(trade_mode="dynamic_dca", market="swap")
    monkeypatch.setattr(
        adapter,
        "config",
        lambda: (_ for _ in ()).throw(
            AssertionError("unused accumulation must stay dormant")
        ),
    )
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup() and runtime.ready
    await runtime.tick()
    assert runtime.status["*"] == "WAIT_ACCUMULATION_MODE"
    assert not client.calls


@pytest.mark.asyncio
async def test_dynamic_dca_mode_blocks_accumulation_candidates_and_pending_rounds(env):
    adapter, client, clock, config, *_ = env
    activation, _ = await setup_activation(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    clock[0] += HOUR
    await runtime.tick()
    assert await model.AccumulationOpportunity.exists()
    config["trade_mode"] = "dynamic_dca"
    clock[0] += 5000
    await runtime.tick()
    assert not client.calls and not runtime._rebased
    config["trade_mode"] = "accumulation"
    await runtime.tick()
    assert not client.calls  # Rebase, never backfill the old signal.


@pytest.mark.asyncio
async def test_review_global_pause_blocks_prepared_submission(env):
    adapter, client, _, config, *_ = env
    operation_id = await prepared(env)
    config["trading_paused"] = True
    result = await AccumulationBuyExecutor(adapter).execute(operation_id)
    assert not client.calls
    assert result.reason == "WAIT_GLOBAL_PAUSE"
    assert (
        await model.PlacementIntent.get(operation_id=operation_id)
    ).state == "rejected"


@pytest.mark.asyncio
async def test_review_global_pause_blocks_runtime_candidates(env):
    adapter, client, clock, config, *_ = env
    await setup_activation(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    config["trading_paused"] = True
    clock[0] += HOUR
    await runtime.tick()
    clock[0] += 5000
    await runtime.tick()
    assert not client.calls
    assert not await model.PlacementIntent.exists()


@pytest.mark.asyncio
async def test_review_empty_adopted_registration_can_pause_resume_and_stop(env):
    from service.accumulation_status import get_accumulation_status

    adapter, client, _, _, *_ = env
    activation, _ = await setup_activation(env)
    lifecycle = AccumulationLifecycleService(adapter.readiness)
    paused = await lifecycle.submit(
        {
            "symbol": activation.symbol,
            "action": "pause",
            "operation_id": "pause-empty",
            "expected_revision": activation.revision,
        },
        account_scope=activation.account_scope,
    )
    detail = await get_accumulation_status(activation.symbol, wait_reasons={})
    assert detail["inventory_restore_required"] is False
    stopped = await lifecycle.submit(
        {
            "symbol": activation.symbol,
            "action": "close",
            "operation_id": "stop-empty",
            "expected_revision": paused.revision,
        },
        account_scope=activation.account_scope,
    )
    assert stopped.state == "stopped" and stopped.status == "applied"
    assert not client.calls and not await model.PlacementIntent.exists()


@pytest.mark.asyncio
async def test_review_retired_unplaced_close_retry_executes_only_new_sale(env):
    from service.accumulation_repair import AccumulationOrderRepair

    adapter, client, _, _, *_ = env
    buy_id = await prepared(env)
    await AccumulationBuyExecutor(adapter).execute(buy_id)
    activation = await model.AccumulationActivation.get(symbol="BTC/USDC")
    holding = await model.OpenTrades.get(id=activation.holding_id)
    client.balance["free"]["BTC"] = holding.accumulation_net_quantity
    lifecycle = AccumulationLifecycleService(adapter.readiness)
    first = await lifecycle.submit(
        {
            "symbol": activation.symbol,
            "action": "close",
            "operation_id": "close-unsent",
            "expected_revision": activation.revision,
        },
        account_scope=activation.account_scope,
    )
    await model.AccumulationLifecycleOperation.filter(
        operation_id=first.operation_id
    ).update(status="quarantined")
    activation.explicitly_paused = True
    await activation.refresh_from_db()
    activation.explicitly_paused = True
    await activation.save()
    retired = await AccumulationOrderRepair(adapter).submit(
        {
            "symbol": activation.symbol,
            "action": "retire_command",
            "operation_id": "retire-unsent",
            "expected_revision": activation.revision,
            "previous_operation_id": first.operation_id,
        }
    )
    retry = await lifecycle.submit(
        {
            "symbol": activation.symbol,
            "action": "retry_close",
            "operation_id": "new-explicit-sale",
            "expected_revision": retired.revision,
            "previous_operation_id": first.operation_id,
        },
        account_scope=activation.account_scope,
    )
    result = await AccumulationCommandExecutor(adapter).execute(retry.operation_id)
    assert result.reason == "SETTLED"
    assert len(client.calls) == 2
    assert await model.PlacementIntent.filter(side="sell").count() == 1


@pytest.mark.asyncio
async def test_review_lost_binance_ack_recovers_commissions_from_only_its_order_executions(
    env, monkeypatch
):
    adapter, client, clock, config, *_ = env
    operation_id = await prepared(env)
    client.failure = TimeoutError()
    await AccumulationBuyExecutor(adapter).execute(operation_id)
    placement = await model.PlacementIntent.get(operation_id=operation_id)
    _, _, side, amount, price, params = client.calls[0]
    normalized = {
        "id": "exchange-1",
        "clientOrderId": params["clientOrderId"],
        "symbol": placement.symbol,
        "side": side,
        "status": "closed",
        "filled": amount,
        "cost": str(Decimal(amount) * Decimal(price)),
        "timestamp": clock[0],
        "fees": [],
        "fee": None,
    }
    client.has = {"fetchOrderTrades": True}
    client.fetch_order = AsyncMock(return_value=normalized)
    client.fetch_order_trades = AsyncMock(
        return_value=[
            {
                "id": "trade-1",
                "order": "exchange-1",
                "symbol": placement.symbol,
                "side": side,
                "amount": amount,
                "fee": {"currency": "USDC", "cost": "0.1"},
            }
        ]
    )
    monkeypatch.setattr(
        adapter.exchange,
        "_Exchange__resolve_symbol_with_refresh",
        AsyncMock(return_value=placement.symbol),
    )
    recovery = AccumulationPlacementRecovery(adapter.exchange, adapter.account_scope)
    assert await recovery.reconcile(placement, config) == "completed"
    checkpoint = await model.AccumulationFillCheckpoint.get(placement=placement)
    assert checkpoint.fees_complete and json.loads(checkpoint.fees_json) == {
        "USDC": "0.1"
    }
    holding = await model.OpenTrades.get(symbol=placement.symbol)
    assert Decimal(holding.accumulation_remaining_cost) == Decimal(
        normalized["cost"]
    ) + Decimal("0.1")
    client.fetch_order_trades.assert_awaited_once_with(
        "exchange-1", placement.symbol, None, 1000
    )
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_accumulation_bybit_eu_reuses_fresh_venue_ceiling_before_quantity_and_submission(
    env,
):
    import time

    adapter, client, _, config, *_ = env
    config["exchange"] = "bybiteu"
    client.id = "bybiteu"
    client.markets["BTC/USDC"]["id"] = "BTCUSDC"
    client.market = lambda symbol: client.markets[symbol]
    client.public_get_v5_market_price_limit = AsyncMock(
        return_value={
            "retCode": 0,
            "result": {
                "symbol": "BTCUSDC",
                "buyLmt": "59.90",
                "ts": str(int(time.time() * 1000)),
            },
        }
    )
    operation_id = await prepared(env)
    client.ask = "59.80"

    async def reject_outside_band(symbol, kind, side, amount, price, params):
        client.calls.append((symbol, kind, side, amount, price, params))
        if Decimal(price) > Decimal("59.90"):
            raise ccxt.InvalidOrder("Bybit EU rejects a price above buyLmt")
        return {
            "id": "band-order",
            "clientOrderId": params["clientOrderId"],
            "symbol": symbol,
            "side": side,
            "status": "closed",
            "filled": amount,
            "cost": str(Decimal(amount) * Decimal(price)),
            "timestamp": adapter.clock_ms(),
            "fees": [{"currency": "USDC", "cost": "0"}],
        }

    client.create_order = reject_outside_band
    result = await AccumulationBuyExecutor(adapter).execute(operation_id)
    assert result.state == "completed"
    assert len(client.calls) == 1 and Decimal(client.calls[0][4]) <= Decimal("59.90")
    client.public_get_v5_market_price_limit.assert_awaited_once()


@pytest.mark.asyncio
async def test_enabled_build_bootstraps_fresh_dry_run_without_credentials(env):
    from service.accumulation_config import accumulation_available

    assert accumulation_available()
    runtime = build_accumulation_runtime(
        lambda: {"dry_run": True, "trade_mode": "dynamic_dca"}
    )
    assert runtime is not None
    assert await runtime.startup() and runtime.ready
    assert runtime.status["*"] == "WAIT_ACCUMULATION_MODE"
    await runtime.shutdown()
    assert not await model.PlacementIntent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("scheduled", [True, False])
async def test_accumulation_obeys_shared_delisting_protection(
    env, monkeypatch, scheduled
):
    import time

    from service.delisting_protection import DelistingEvent, DelistingProtectionService

    adapter, client, _, config, *_ = env
    operation_id = await prepared(env)
    config["delisting_protection_enabled"] = True
    protection = DelistingProtectionService()
    protection._fingerprint = protection._build_fingerprint(config)
    protection._markets = {"BTC/USDC": {"id": "BTCUSDC", "active": True}}
    protection._market_verified = True
    protection._market_checked_at = time.monotonic()
    protection._schedule_checked_at = time.monotonic()
    protection._schedule_verified = scheduled
    if scheduled:
        protection._events_by_market_id["BTCUSDC"] = DelistingEvent(
            "binance", "BTCUSDC", "BTC/USDC", 1900000000000, "binance_spot_schedule"
        )
    protection.ensure_fresh = AsyncMock()
    monkeypatch.setattr(DelistingProtectionService, "_instance", protection)

    result = await AccumulationBuyExecutor(adapter).execute(operation_id)

    assert not client.calls
    assert result.reason == (
        "blocked_scheduled_delisting"
        if scheduled
        else "blocked_delisting_check_unavailable"
    )
    assert (
        await model.PlacementIntent.get(operation_id=operation_id)
    ).state == "rejected"
    protection.ensure_fresh.assert_awaited_once_with(config)


@pytest.mark.asyncio
async def test_accumulation_rechecks_delisting_snapshot_at_durable_claim(
    env, monkeypatch
):
    import time

    from service.delisting_protection import DelistingProtectionService

    adapter, client, _, config, *_ = env
    operation_id = await prepared(env)
    config["delisting_protection_enabled"] = True
    protection = DelistingProtectionService()
    protection._fingerprint = protection._build_fingerprint(config)
    protection._markets = {"BTC/USDC": {"id": "BTCUSDC", "active": True}}
    protection._market_verified = protection._schedule_verified = True
    protection._market_checked_at = protection._schedule_checked_at = time.monotonic()
    protection.ensure_fresh = AsyncMock()
    monkeypatch.setattr(DelistingProtectionService, "_instance", protection)
    executor = AccumulationBuyExecutor(adapter)
    from service import accumulation_execution

    usable = accumulation_execution.usable_accumulation_quote

    async def lose_verification_during_budget_read(*args, **kwargs):
        result = await usable(*args, **kwargs)
        protection._schedule_verified = False
        return result

    monkeypatch.setattr(
        accumulation_execution,
        "usable_accumulation_quote",
        lose_verification_during_budget_read,
    )
    result = await executor.execute(operation_id)
    assert not client.calls
    assert result.reason == "blocked_delisting_check_unavailable"
    assert (
        await model.PlacementIntent.get(operation_id=operation_id)
    ).state == "rejected"


@pytest.mark.asyncio
async def test_lowercase_configured_quote_can_execute_and_account_managed_inventory(
    env,
):
    adapter, client, _, config, *_ = env
    config["currency"] = "usdc"
    # Runtime admission receives the adapter's canonical configuration snapshot.
    normalized_env = (*env[:3], adapter.config(), *env[4:])
    operation_id = await prepared(normalized_env)
    result = await AccumulationBuyExecutor(adapter).execute(operation_id)
    assert result.state == "completed" and len(client.calls) == 1
    usage = await CapitalBudgetService()._load_usage(config)
    assert usage.unavailable_reason is None


@pytest.mark.asyncio
async def test_demo_accumulation_runtime_buys_through_exchange_and_accounts(env):
    adapter, client, clock, config, *_ = env
    config["dry_run"] = True
    activation, _ = await setup_activation(env)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    clock[0] += HOUR
    await runtime.tick()
    clock[0] += 5000
    await runtime.tick()
    assert len(client.calls) == 1
    assert (await model.PlacementIntent.get()).state == "completed"
    assert await model.OpenTrades.filter(lifecycle_mode="accumulation").exists()
    assert activation.account_scope != accumulation_account_scope(
        {**config, "dry_run": False}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["rebind_account", "declare_ownership"])
async def test_demo_inventory_cannot_be_rebound_into_live_ownership(env, action):
    from service.accumulation_account_rebind import AccumulationAccountRebind
    from service.accumulation_ownership_declaration import (
        AccumulationOwnershipDeclaration,
    )
    from service.accumulation_state import AccumulationConflictError

    adapter, client, _, config, *_ = env
    config["dry_run"] = True
    activation, _ = await setup_activation(env)
    config["dry_run"] = False
    request = {
        "symbol": activation.symbol,
        "action": action,
        "operation_id": "cross-environment-declaration",
        "expected_revision": activation.revision,
    }
    if action == "declare_ownership":
        request.update(confirmation=activation.symbol, note="Review ownership")
        service = AccumulationOwnershipDeclaration(adapter)
    else:
        service = AccumulationAccountRebind(adapter)
    with pytest.raises(AccumulationConflictError, match="Demo and live"):
        await service.submit(request)
    assert not client.calls and not await model.AccumulationLifecycleOperation.exists()


@pytest.mark.asyncio
async def test_demo_signal_loader_runs_asap_registration_and_strategy_buy(
    env, monkeypatch
):
    from service.signal import Signal
    from service.signal_runtime import get_active_open_symbols

    adapter, client, clock, config, *_ = env
    await _entry_service(env, monkeypatch, signal="asap")
    config.update(dry_run=True, bo=25)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    queue = asyncio.Queue()
    signal = Signal(queue)
    signal.accumulation_entry = runtime.entry
    try:
        await signal._reload_plugin(dict(config))
        assert signal.signal_name == "asap" and signal._task is not None
        assert await asyncio.wait_for(queue.get(), 2) == ["BTC/USDC"]
        activation = await model.AccumulationActivation.get(symbol="BTC/USDC")
        assert activation.state == "enabled" and not client.calls
        assert await get_active_open_symbols() == ["BTC/USDC"]
        await runtime.tick()  # ASAP opens immediately; no strategy candle is required.
        assert len(client.calls) == 1
        assert (await model.PlacementIntent.get()).state == "completed"
    finally:
        await signal.shutdown()
        await runtime.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("begin_number", [1, 2, 3, 4])
async def test_asap_reload_cancellation_during_sqlite_begin_keeps_database_available(
    env, monkeypatch, begin_number
):
    from service.signal import Signal
    from tortoise.backends.sqlite.client import SqliteTransactionWrapper
    from tortoise.connection import connections

    adapter, _, _, config, *_ = env
    await _entry_service(env, monkeypatch, signal="asap")
    config["dry_run"] = True
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    signal = Signal(asyncio.Queue())
    signal.accumulation_entry = runtime.entry
    entered = asyncio.Event()
    release = asyncio.Event()
    original = SqliteTransactionWrapper.begin
    connection = connections.get("default")

    begins = 0

    async def interrupted_begin(self):
        nonlocal begins
        begins += 1
        if begins == begin_number:
            entered.set()
            await release.wait()
        await original(self)

    monkeypatch.setattr(SqliteTransactionWrapper, "begin", interrupted_begin)
    try:
        await signal._reload_plugin(dict(config))
        await asyncio.wait_for(entered.wait(), 1)
        assert signal._task is not None
        signal._task.cancel()
        await asyncio.sleep(0)  # Deliver cancellation while transaction entry is gated.
        release.set()
        await asyncio.wait_for(signal.shutdown(), 2)
        assert (
            await asyncio.wait_for(model.AccumulationActivation.all().count(), 0.3) == 1
        )
    finally:
        release.set()
        # A failing reproduction must not leave the isolated test connection stuck.
        if connection._lock.locked():
            connection._lock.release()
        await signal.shutdown()
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_asap_initial_buy_does_not_wait_for_strategy_history_and_survives_restart(
    env, monkeypatch
):
    """ASAP buys at a rising ask without a candle; strategy warmup follows the fill."""
    service, _ = await _entry_service(env, monkeypatch, signal="asap")
    adapter, client, clock, config, *_ = env
    config["bo"] = 25
    client.ask = "110"  # Above every historical close; no dip signal exists.
    history = AsyncMock(side_effect=AccumulationStateError("history unavailable"))
    monkeypatch.setattr(adapter, "candles", history)
    assert (await service.asap())[0].reason == "ENABLED"
    assert not (await model.AccumulationActivation.get()).observations_initialized
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    await runtime.tick()
    assert len(client.calls) == 1
    history.assert_not_awaited()
    holding = await model.OpenTrades.get(symbol="BTC/USDC")
    assert holding.lifecycle_mode == "accumulation" and holding.amount > 0
    opportunity = await model.AccumulationOpportunity.get(is_initial_entry=True)
    assert opportunity.consumed_at is not None
    activation = await model.AccumulationActivation.get()
    assert activation.consumption_revision == 0
    assert activation.execution_guard_json is None  # No invented ATR for ASAP.
    await runtime.tick()
    assert history.await_count == 1  # Only subsequent buys require strategy history.
    assert len(client.calls) == 1
    restarted = AccumulationRuntime(adapter)
    assert await restarted.startup()
    await restarted.tick()
    assert len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", ["budget", "paused", "unknown_response"])
async def test_asap_base_order_keeps_capital_pause_and_single_submission_guards(
    env, monkeypatch, blocker
):
    service, _ = await _entry_service(env, monkeypatch, signal="asap")
    adapter, client, clock, config, *_ = env
    config["bo"] = 25
    assert (await service.asap())[0].reason == "ENABLED"
    if blocker == "budget":
        client.balance["free"]["USDC"] = "1"
    elif blocker == "paused":
        config["trading_paused"] = True
    else:
        client.failure = TimeoutError("response lost")
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    await runtime.tick()
    await runtime.tick()
    assert len(client.calls) == (1 if blocker == "unknown_response" else 0)
    assert not await model.OpenTrades.exists()
    if blocker == "unknown_response":
        assert (await model.PlacementIntent.get()).state == "indeterminate"
        assert await model.AccumulationOpportunity.filter(
            unresolved_slot=(await model.AccumulationActivation.get()).id
        ).exists()


@pytest.mark.asyncio
async def test_initial_fill_then_strategy_rebase_and_dip_uses_normal_guard(
    env, monkeypatch
):
    service, _ = await _entry_service(env, monkeypatch, signal="asap")
    adapter, client, clock, config, *_ = env
    config["bo"] = 25
    await service.asap()
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    await runtime.tick()
    assert len(client.calls) == 1
    client.balance["free"]["BTC"] = (
        await model.OpenTrades.get()
    ).accumulation_net_quantity
    await runtime.tick()  # Strategy observations are initialized after the base order.
    activation = await model.AccumulationActivation.get()
    assert activation.observations_initialized
    assert (
        await model.AccumulationStrategyState.get()
    ).last_processed_close_ms == 600 * HOUR
    clock[0] += HOUR
    await runtime.tick()
    clock[0] += 5000
    await runtime.tick()
    # A fresh declining candle now belongs to the accumulation strategy.
    assert len(client.calls) == 2
    activation = await model.AccumulationActivation.get()
    assert activation.consumption_revision == 1
    assert Decimal(json.loads(activation.execution_guard_json)["signal_atr"]) > 0
    assert (
        await model.AccumulationOpportunity.filter(is_initial_entry=True).count() == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_requested", [False, True])
async def test_runtime_resumes_pending_asap_entry_with_same_request_and_buys_bo(
    env, monkeypatch, retry_requested
):
    """A pre-upgrade validation failure must not permanently park an ASAP signal."""
    service, _ = await _entry_service(env, monkeypatch, signal="asap")
    adapter, client, _, config, *_ = env
    original = adapter.readiness
    monkeypatch.setattr(
        adapter,
        "readiness",
        AsyncMock(side_effect=AccumulationStateError("old warmup failed")),
    )
    entry = (await service.asap())[0]
    if retry_requested:
        await service.submit_staged(await _staged_payload(entry))
    latest = await model.AccumulationLifecycleOperation.all().order_by("-id").first()
    operation_id = latest.operation_id
    before = await model.AccumulationLifecycleOperation.all().count()
    monkeypatch.setattr(adapter, "readiness", original)
    config["bo"] = 100
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    await runtime.tick()
    assert len(client.calls) == 1
    assert (await model.PlacementIntent.get()).requested_quote == 100
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id=operation_id)
    ).status == "applied"
    assert await model.AccumulationLifecycleOperation.all().count() == before
    await runtime.tick()
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_runtime_does_not_automatically_adopt_pending_csv_inventory(
    env, monkeypatch
):
    service, _ = await _entry_service(env, monkeypatch)
    adapter, client, *_ = env
    entry = (await service.csv(ENTRY_CSV))[0]
    client.balance["free"]["BTC"] = "2"
    adapter.readiness = AsyncMock(wraps=adapter.readiness)
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    await runtime.tick()
    adapter.readiness.assert_not_awaited()
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id=entry.operation_id)
    ).status == "pending"
    assert not client.calls and not await model.OpenTrades.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", ["pause", "abandon", "quarantine", "account"])
async def test_pending_asap_recovery_preserves_operator_and_account_blocks(
    env, monkeypatch, blocker
):
    service, _ = await _entry_service(env, monkeypatch, signal="asap")
    adapter, client, _, config, *_ = env
    original = adapter.readiness
    monkeypatch.setattr(
        adapter, "readiness", AsyncMock(side_effect=AccumulationStateError("not ready"))
    )
    entry = (await service.asap())[0]
    monkeypatch.setattr(adapter, "readiness", original)
    if blocker == "pause":
        config["trading_paused"] = True
    elif blocker == "abandon":
        await service.submit_staged(await _staged_payload(entry, "abandon_entry"))
    elif blocker == "quarantine":
        await model.AccumulationLifecycleOperation.filter(
            operation_id=entry.operation_id
        ).update(status="quarantined")
    else:
        config["key"] = "different-account"
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    await runtime.tick()
    assert not client.calls and not await model.OpenTrades.exists()


@pytest.mark.asyncio
async def test_shutdown_during_pending_asap_validation_does_not_place_bo(
    env, monkeypatch
):
    service, _ = await _entry_service(env, monkeypatch, signal="asap")
    adapter, client, *_ = env
    original = adapter.readiness
    monkeypatch.setattr(
        adapter, "readiness", AsyncMock(side_effect=AccumulationStateError("not ready"))
    )
    await service.asap()
    runtime = AccumulationRuntime(adapter)

    async def stop_after_validation(request):
        ready = await original(request)
        runtime.request_stop()
        return ready

    monkeypatch.setattr(adapter, "readiness", stop_after_validation)
    assert await runtime.startup()
    await runtime.tick()
    assert not client.calls and not await model.PlacementIntent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["buy", "wallet", "sale"])
@pytest.mark.parametrize(
    "evidence",
    [
        "account_update",
        "unknown_timestamp",
        "other_venue",
        "future_update",
        "slow_request",
    ],
)
async def test_balance_freshness_distinguishes_account_updates_from_observation(
    env, path, evidence
):
    """Binance updateTime can be old even on a freshly authenticated response."""
    adapter, client, clock, config, *_ = env
    client.balance["free"]["BTC"] = "1"
    stamp = clock[0] - 27 * HOUR
    client.balance["timestamp"] = stamp
    client.balance["info"] = {"updateTime": stamp}
    if evidence == "other_venue":
        client.id = "bybit"
    elif evidence == "unknown_timestamp":
        client.balance["info"] = {}
    elif evidence == "future_update":
        client.balance["timestamp"] = clock[0] + 1
        client.balance["info"]["updateTime"] = clock[0] + 1
    elif evidence == "slow_request":
        original = client.fetch_balance

        async def delayed():
            result = await original()
            clock[0] += 10001
            return result

        client.fetch_balance = delayed

    async def read():
        if path == "buy":
            return (
                await adapter.read_inputs("BTC/USDC", config)
            ).funding.observed_at_ms
        if path == "wallet":
            return (await adapter.account_inventory("BTC/USDC", config)).observed_at_ms
        return (await adapter.sale_inputs("BTC/USDC", "0.1", config)).observed_at_ms

    if evidence == "account_update":
        assert await read() == clock[0]
        assert client.balance["timestamp"] == stamp
    else:
        with pytest.raises(AccumulationStateError, match="stale|future"):
            await read()
    assert not client.calls


@pytest.mark.asyncio
async def test_asap_can_open_bo_from_fresh_binance_balance_with_old_account_update(
    env, monkeypatch
):
    service, _ = await _entry_service(env, monkeypatch, signal="asap")
    adapter, client, clock, *_ = env
    stamp = clock[0] - 27 * HOUR
    client.balance.update(timestamp=stamp, info={"updateTime": stamp})
    assert (await service.asap())[0].reason == "ENABLED"
    runtime = AccumulationRuntime(adapter)
    assert await runtime.startup()
    await runtime.tick()
    assert len(client.calls) == 1
    assert (await model.PlacementIntent.get()).state == "completed"
