"""Real SQLite fill, fee, crash and recovery coverage for accumulation."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import model
import pytest
import pytest_asyncio
from service.accumulation_accounting import persist_accumulation_order
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_fill import (
    AccumulationFill,
    AccumulationInventory,
    apply_fill_delta,
)
from service.accumulation_lifecycle import AccumulationLifecycleService
from service.accumulation_performance import accumulation_performance
from service.accumulation_recovery import AccumulationPlacementRecovery
from service.accumulation_state import AccumulationConflictError
from service.exchange_capabilities import (
    ExchangeOrderLookupResult,
    ExchangeOrderLookupStatus,
)
from service.lifecycle_mutation import LifecycleMutationCoordinator
from service.placement_intents import PlacementIntentService, PlacementIntentState
from service.placement_reconciliation import PlacementReconciler
from service.trading_maintenance import TradingMaintenanceBarrier
from tortoise import Tortoise
from tortoise.exceptions import OperationalError


@pytest_asyncio.fixture
async def accounting_db(tmp_path, monkeypatch):
    url = f"sqlite://{tmp_path / 'accounting.sqlite'}"
    await Tortoise.init(db_url=url, modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    coordinator = LifecycleMutationCoordinator(TradingMaintenanceBarrier())
    for module in (
        "accumulation_accounting",
        "accumulation_lifecycle",
        "accumulation_repair",
        "accumulation_account_rebind",
    ):
        monkeypatch.setattr(
            f"service.{module}.lifecycle_mutation_coordinator", coordinator
        )
    yield url
    await Tortoise.close_connections()


async def _buy():
    version = await model.StrategyVersion.create(
        strategy_slug="accumulation",
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="fixture",
    )
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC",
        account_scope="account-1",
        state="enabled",
        explicitly_paused=False,
        strategy_version=version,
    )
    opportunity = await model.AccumulationOpportunity.create(
        activation=activation,
        generation=activation.generation,
        strategy_version=version,
        observation_epoch=0,
        signal_close_ms=1000,
        expires_at_ms=int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000
        ),
        signal_price="97",
        signal_atr="2",
        unresolved_slot=activation.id,
    )
    placement = await model.PlacementIntent.create(
        operation_id="buy-1",
        symbol="BTC/USDC",
        exchange_name="binance",
        exchange_order_id="exchange-buy-1",
        side="buy",
        action="buy",
        order_type="market",
        state="accepted",
        reserved_quote=1000,
    )
    await model.AccumulationAttempt.create(opportunity=opportunity, placement=placement)
    return activation, opportunity, placement


def _order(*, filled="10", cost="100", status="closed", fees=None, side="buy"):
    return {
        "id": f"exchange-{side}-1",
        "symbol": "BTC/USDC",
        "side": side,
        "filled": filled,
        "cost": cost,
        "status": status,
        "timestamp": 2000,
        "fees": [{"currency": "USDC", "cost": "0"}] if fees is None else fees,
    }


async def _rebind_fixture():
    from service.accumulation_exchange import AccumulationWalletEvidence
    from service.exchange_capabilities import build_client_order_id

    activation, _, placement = await _buy()
    placement.operation_id = "buy-" + "a" * 32
    placement.client_order_id = build_client_order_id(placement.operation_id)
    await placement.save()
    evidence = {**_order(), "clientOrderId": placement.client_order_id}
    await _persist(evidence, placement.operation_id)
    await _complete(placement.operation_id)
    await activation.refresh_from_db()
    config = {"exchange": "binance", "dry_run": False, "market": "spot"}
    clock = [1000]
    adapter = SimpleNamespace(
        config=lambda: dict(config),
        clock_ms=lambda: clock[0],
        account_scope=AsyncMock(return_value="rotated-account-scope"),
        account_inventory=AsyncMock(
            return_value=AccumulationWalletEvidence("rotated-account-scope", "10", 1000)
        ),
        exchange=SimpleNamespace(
            lookup_spot_order=AsyncMock(
                return_value=ExchangeOrderLookupResult(
                    ExchangeOrderLookupStatus.FOUND, evidence
                )
            )
        ),
    )
    payload = {
        "symbol": activation.symbol,
        "action": "rebind_account",
        "operation_id": "rebind-1",
        "expected_revision": activation.revision,
    }
    return activation, placement, adapter, payload, config, clock


@pytest.mark.asyncio
async def test_rebind_proves_original_orders_and_inventory_without_changing_the_ledger(
    accounting_db,
):
    from service.accumulation_account_rebind import AccumulationAccountRebind

    activation, placement, adapter, payload, *_ = await _rebind_fixture()
    before = await model.OpenTrades.all().values()
    guard, generation, pin = (
        activation.execution_guard_json,
        activation.generation,
        activation.strategy_version_id,
    )
    result = await AccumulationAccountRebind(adapter).submit(payload)
    assert result.status == "applied" and result.state == "paused"
    await activation.refresh_from_db()
    assert (
        activation.account_scope == "rotated-account-scope"
        and activation.explicitly_paused
    )
    assert (
        activation.execution_guard_json == guard and activation.generation == generation
    )
    assert (
        activation.strategy_version_id == pin and activation.consumption_revision == 1
    )
    assert before == await model.OpenTrades.all().values()
    assert (await model.PlacementIntent.get(id=placement.id)).state == "completed"
    assert await AccumulationAccountRebind(adapter).submit(payload) == result
    assert adapter.exchange.lookup_spot_order.await_count == 1
    assert adapter.account_inventory.await_count == 1
    assert await model.PlacementIntent.all().count() == 1
    assert not await model.AccumulationLifecycleOperation.filter(
        status="pending"
    ).exists()
    with pytest.raises(AccumulationConflictError):
        await AccumulationAccountRebind(adapter).submit(
            {**payload, "expected_revision": 0}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch",
    [
        "client",
        "amount",
        "fees",
        "wallet",
        "scope",
        "stale",
        "config",
        "revision",
        "inventory",
    ],
)
async def test_rebind_never_adopts_different_account_or_stale_evidence(
    accounting_db, mismatch
):
    from dataclasses import replace as update

    from service.accumulation_account_rebind import AccumulationAccountRebind

    activation, placement, adapter, payload, config, clock = await _rebind_fixture()
    evidence = dict(adapter.exchange.lookup_spot_order.return_value.order)
    if mismatch == "client":
        evidence["clientOrderId"] = "another-account-client-id"
    elif mismatch == "amount":
        evidence["filled"] = "9"
    elif mismatch == "fees":
        evidence["fees"] = [{"currency": "USDC", "cost": "1"}]
    adapter.exchange.lookup_spot_order.return_value = ExchangeOrderLookupResult(
        ExchangeOrderLookupStatus.FOUND, evidence
    )
    wallet = adapter.account_inventory.return_value
    if mismatch == "wallet":
        adapter.account_inventory.return_value = update(
            wallet, free_base="9.999999999999999999"
        )
    elif mismatch == "scope":
        adapter.account_inventory.return_value = update(
            wallet, account_scope="another-scope"
        )
    elif mismatch == "stale":
        clock[0] = 12000
    elif mismatch in {"config", "revision", "inventory"}:

        async def changed(*args):
            if mismatch == "config":
                config["key"] = "changed-during-verification"
            elif mismatch == "revision":
                await model.AccumulationActivation.filter(id=activation.id).update(
                    revision=99
                )
            else:
                await model.OpenTrades.filter(id=activation.holding_id).update(
                    accumulation_net_quantity="11"
                )
            return wallet

        adapter.account_inventory.side_effect = changed
    with pytest.raises(AccumulationConflictError):
        await AccumulationAccountRebind(adapter).submit(payload)
    await activation.refresh_from_db()
    assert activation.account_scope == "account-1" and activation.explicitly_paused
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id="rebind-1")
    ).status == "quarantined"
    assert await model.PlacementIntent.all().count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blocked", ["csv", "missing_client", "pending_order", "incomplete_fees", "venue"]
)
async def test_rebind_requires_settled_native_same_venue_proof(accounting_db, blocked):
    from service.accumulation_account_rebind import AccumulationAccountRebind

    activation, placement, adapter, payload, config, *_ = await _rebind_fixture()
    if blocked == "csv":
        await model.OpenTrades.filter(id=activation.holding_id).update(
            execution_history_complete=False
        )
    elif blocked == "missing_client":
        await model.PlacementIntent.filter(id=placement.id).update(
            client_order_id=None,
            result_json=None,
            operation_id="legacy-identity-unavailable",
        )
    elif blocked == "pending_order":
        await model.PlacementIntent.filter(id=placement.id).update(state="accepted")
    elif blocked == "incomplete_fees":
        await model.AccumulationFillCheckpoint.filter(activation=activation).update(
            fees_complete=False
        )
    else:
        config["exchange"] = "different-exchange"
    with pytest.raises(AccumulationConflictError):
        await AccumulationAccountRebind(adapter).submit(payload)
    assert not await model.AccumulationLifecycleOperation.filter(
        action="rebind_account"
    ).exists()
    adapter.exchange.lookup_spot_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_rebind_unknown_lookup_is_explicitly_retryable_without_enabling_buys(
    accounting_db,
):
    from service.accumulation_account_rebind import AccumulationAccountRebind

    activation, _, adapter, payload, *_ = await _rebind_fixture()
    found = adapter.exchange.lookup_spot_order.return_value
    adapter.exchange.lookup_spot_order.return_value = ExchangeOrderLookupResult(
        ExchangeOrderLookupStatus.NOT_FOUND
    )
    result = await AccumulationAccountRebind(adapter).submit(payload)
    assert result.status == "quarantined"
    await activation.refresh_from_db()
    assert activation.account_scope == "account-1" and activation.explicitly_paused
    adapter.exchange.lookup_spot_order.return_value = found
    assert (
        await AccumulationAccountRebind(adapter).submit(payload)
    ).status == "applied"
    assert (
        await model.AccumulationLifecycleOperation.filter(
            action="rebind_account"
        ).count()
        == 1
    )


@pytest.mark.asyncio
async def test_rebind_scope_commit_failure_keeps_original_binding_and_retry_journal(
    accounting_db, monkeypatch
):
    from service.accumulation_account_rebind import AccumulationAccountRebind

    activation, _, adapter, payload, *_ = await _rebind_fixture()
    original = model.AccumulationActivation.save

    async def failed(self, *args, **kwargs):
        if self.account_scope == "rotated-account-scope":
            raise RuntimeError("scope commit failed")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(model.AccumulationActivation, "save", failed)
    with pytest.raises(RuntimeError, match="scope commit failed"):
        await AccumulationAccountRebind(adapter).submit(payload)
    await activation.refresh_from_db()
    assert activation.account_scope == "account-1" and activation.explicitly_paused
    assert (
        await model.AccumulationLifecycleOperation.get(operation_id="rebind-1")
    ).status == "quarantined"


@pytest.mark.asyncio
async def test_two_dashboards_cannot_rebind_the_same_revision_twice(accounting_db):
    from service.accumulation_account_rebind import AccumulationAccountRebind

    activation, _, adapter, payload, *_ = await _rebind_fixture()
    results = await asyncio.gather(
        *[
            AccumulationAccountRebind(adapter).submit(
                {**payload, "operation_id": f"rotate-{index}"}
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
            action="rebind_account"
        ).count()
        == 1
    )
    assert (
        await model.AccumulationActivation.get(id=activation.id)
    ).account_scope == "rotated-account-scope"


async def _persist(order, operation_id="buy-1"):
    return await persist_accumulation_order(
        operation_id, order, account_scope="account-1", exchange_name="binance"
    )


async def _complete(operation_id="buy-1"):
    await PlacementIntentService().transition(
        operation_id, PlacementIntentState.COMPLETED
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["partial", "closing", "stopped"])
async def test_rebind_checks_first_and_last_order_and_preserves_close_semantics(
    accounting_db, mode
):
    from service.accumulation_account_rebind import AccumulationAccountRebind
    from service.accumulation_exchange import AccumulationWalletEvidence

    activation, buy, adapter, payload, *_ = await _rebind_fixture()
    first_evidence = adapter.exchange.lookup_spot_order.return_value.order
    sale = await _sell(
        activation, action="sell_partial" if mode == "partial" else "close"
    )
    from service.exchange_capabilities import build_client_order_id

    sale.operation_id = "sell-" + "b" * 32
    sale.client_order_id = build_client_order_id(sale.operation_id)
    await sale.save()
    filled = "10" if mode == "stopped" else "2"
    last_evidence = {
        **_order(side="sell", filled=filled, cost=str(int(filled) * 11)),
        "clientOrderId": sale.client_order_id,
    }
    await _persist(last_evidence, sale.operation_id)
    await _complete(sale.operation_id)
    if mode == "closing":
        await activation.refresh_from_db()
        await model.AccumulationLifecycleOperation.filter(
            operation_id="manual-1"
        ).update(status="reconciled", result_revision=activation.revision)
        activation.explicitly_paused = True
        await activation.save()
    else:
        await AccumulationLifecycleService().complete_settlement(
            "manual-1", account_scope="account-1"
        )
    await activation.refresh_from_db()
    payload["expected_revision"] = activation.revision
    adapter.exchange.lookup_spot_order.side_effect = lambda symbol, config, **ids: (
        ExchangeOrderLookupResult(
            ExchangeOrderLookupStatus.FOUND,
            first_evidence
            if ids["exchange_order_id"] == buy.exchange_order_id
            else last_evidence,
        )
    )
    adapter.account_inventory.return_value = AccumulationWalletEvidence(
        "rotated-account-scope", "0" if mode == "stopped" else "8", 1000
    )
    result = await AccumulationAccountRebind(adapter).submit(payload)
    assert result.state == ("paused" if mode == "partial" else mode)
    assert adapter.exchange.lookup_spot_order.await_count == 2
    if mode == "closing":
        await activation.refresh_from_db()
        result = await AccumulationLifecycleService().submit(
            {
                "symbol": activation.symbol,
                "action": "retry_close",
                "operation_id": "new-key-explicit-sale",
                "expected_revision": activation.revision,
                "previous_operation_id": "manual-1",
            },
            account_scope="rotated-account-scope",
        )
        assert result.status == "pending" and result.state == "closing"
        assert await model.PlacementIntent.all().count() == 2


def _repair_adapter(order=None, status=ExchangeOrderLookupStatus.FOUND):
    config = {"exchange": "binance", "dry_run": False, "market": "spot"}
    return SimpleNamespace(
        config=lambda: dict(config),
        account_scope=AsyncMock(return_value="account-1"),
        exchange=SimpleNamespace(
            lookup_spot_order=AsyncMock(
                return_value=ExchangeOrderLookupResult(status, order)
            )
        ),
    )


async def _quarantine(activation, placement):
    placement.state = "restored_quarantined"
    await placement.save()
    await activation.refresh_from_db()
    activation.explicitly_paused = True
    if activation.state == "enabled":
        activation.state = "paused"
    await activation.save()
    return {
        "symbol": activation.symbol,
        "action": "repair_order",
        "operation_id": "repair-1",
        "expected_revision": activation.revision,
        "placement_operation_id": placement.operation_id,
    }


@pytest.mark.asyncio
async def test_explicit_repair_applies_only_terminal_buy_delta_and_preserves_pause(
    accounting_db,
):
    from service.accumulation_repair import AccumulationOrderRepair

    activation, opportunity, placement = await _buy()
    await _persist(_order(filled="3", cost="30", status="open"))
    request = await _quarantine(activation, placement)
    guard = activation.execution_guard_json
    adapter = _repair_adapter(_order())
    repair = AccumulationOrderRepair(adapter)
    result = await repair.submit(request)
    assert result.status == "applied" and result.state == "paused"
    holding = await model.OpenTrades.get(id=activation.holding_id)
    assert Decimal(holding.accumulation_net_quantity) == 10
    await activation.refresh_from_db()
    assert activation.explicitly_paused and activation.execution_guard_json == guard
    assert activation.consumption_revision == 1
    await placement.refresh_from_db()
    assert placement.state == "completed"
    assert (
        await model.AccumulationOpportunity.get(id=opportunity.id)
    ).unresolved_slot is None
    assert await AccumulationOrderRepair(adapter).submit(request) == result
    assert adapter.exchange.lookup_spot_order.await_count == 1
    assert await model.TradeExecutions.all().count() == 2
    with pytest.raises(AccumulationConflictError):
        await repair.submit({**request, "placement_operation_id": "another"})


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence", [None, _order(status="open"), _order(fees=[])])
async def test_repair_keeps_unknown_open_or_incomplete_orders_quarantined(
    accounting_db, evidence
):
    from service.accumulation_repair import AccumulationOrderRepair

    activation, opportunity, placement = await _buy()
    request = await _quarantine(activation, placement)
    adapter = _repair_adapter(evidence)
    result = await AccumulationOrderRepair(adapter).submit(request)
    assert result.status == "quarantined"
    assert await model.OpenTrades.all().count() == 0
    await placement.refresh_from_db()
    assert placement.state == "restored_quarantined"
    assert (
        await model.AccumulationOpportunity.get(id=opportunity.id)
    ).unresolved_slot == activation.id
    adapter.exchange.lookup_spot_order.return_value = ExchangeOrderLookupResult(
        ExchangeOrderLookupStatus.FOUND, _order()
    )
    assert (await AccumulationOrderRepair(adapter).submit(request)).status == "applied"
    assert (
        await model.AccumulationLifecycleOperation.filter(action="repair_order").count()
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,filled,state",
    [
        ("close", "4", "closing"),
        ("close", "10", "stopped"),
        ("sell_partial", "2", "paused"),
    ],
)
async def test_repaired_sale_never_replays_and_close_dust_requires_explicit_retry(
    accounting_db, action, filled, state
):
    from service.accumulation_repair import AccumulationOrderRepair

    activation, _, _ = await _buy()
    await _persist(_order())
    await _complete()
    placement = await _sell(activation, action=action)
    placement.request_json = json.dumps(
        {**json.loads(placement.request_json), "generation": str(activation.generation)}
    )
    operation = await model.AccumulationLifecycleOperation.get(operation_id="manual-1")
    operation.status = "quarantined"
    await operation.save()
    request = await _quarantine(activation, placement)
    adapter = _repair_adapter(
        _order(side="sell", filled=filled, cost=str(int(filled) * 11))
    )
    result = await AccumulationOrderRepair(adapter).submit(request)
    assert result.state == state
    await activation.refresh_from_db()
    assert activation.explicitly_paused
    await operation.refresh_from_db()
    assert operation.status == ("reconciled" if state == "closing" else "applied")
    assert (
        await model.AccumulationLifecycleOperation.filter(status="pending").count() == 0
    )
    if state == "closing":
        assert (
            await model.OpenTrades.get(id=activation.holding_id)
        ).accumulation_net_quantity == "6"
        retried = await AccumulationLifecycleService().submit(
            {
                "symbol": activation.symbol,
                "action": "retry_close",
                "operation_id": "new-sale-authorization",
                "expected_revision": activation.revision,
                "previous_operation_id": operation.operation_id,
            },
            account_scope="account-1",
        )
        assert retried.status == "pending"


@pytest.mark.asyncio
async def test_repair_rechecks_revision_after_lookup_and_rolls_back_bad_evidence(
    accounting_db,
):
    from service.accumulation_repair import AccumulationOrderRepair

    activation, _, placement = await _buy()
    request = await _quarantine(activation, placement)
    adapter = _repair_adapter(_order())

    async def changed(*args, **kwargs):
        await model.AccumulationActivation.filter(id=activation.id).update(revision=99)
        return ExchangeOrderLookupResult(ExchangeOrderLookupStatus.FOUND, _order())

    adapter.exchange.lookup_spot_order.side_effect = changed
    with pytest.raises(AccumulationStateError, match="unchanged paused"):
        await AccumulationOrderRepair(adapter).submit(request)
    await placement.refresh_from_db()
    assert placement.state == "restored_quarantined"
    assert await model.OpenTrades.all().count() == 0
    assert await model.AccumulationFillCheckpoint.all().count() == 0


async def _sell(activation, action="sell_partial", quantity="2"):
    await activation.refresh_from_db()
    payload = {
        "symbol": activation.symbol,
        "operation_id": "manual-1",
        "action": action,
        "expected_revision": activation.revision,
    }
    if action == "sell_partial":
        payload["quantity"] = quantity
    await AccumulationLifecycleService().submit(payload, account_scope="account-1")
    operation = await model.AccumulationLifecycleOperation.get(operation_id="manual-1")
    placement = await model.PlacementIntent.create(
        operation_id="sell-1",
        symbol="BTC/USDC",
        exchange_name="binance",
        exchange_order_id="exchange-sell-1",
        side="sell",
        action="sell",
        order_type="market",
        state="accepted",
        request_json=json.dumps(
            {"accumulation_operation_id": "manual-1", "accumulation_action": action}
        ),
    )
    operation.placement = placement
    await operation.save()
    return placement


def _performance_adapter():
    return SimpleNamespace(
        config=lambda: {"exchange": "binance"},
        account_scope=AsyncMock(return_value="account-1"),
        clock_ms=lambda: 1000,
        mark_quotes=AsyncMock(
            return_value={"BTC/USDC": {"bid": "12", "observed_at_ms": 1000}}
        ),
    )


@pytest.mark.asyncio
async def test_performance_exact_partial_sale_and_duplicate_cumulative_evidence(
    accounting_db,
):
    activation, _, _ = await _buy()
    await _persist(_order(fees=[{"currency": "USDC", "cost": "1"}]))
    await _complete()
    adapter = _performance_adapter()
    report = await accumulation_performance(adapter)
    group = report["by_quote"][0]
    assert report["complete"]
    assert Decimal(group["market_value"]) == 120
    assert Decimal(group["unrealized"]) == 19 and Decimal(group["realized"]) == 0
    await _sell(activation)
    order = _order(
        side="sell", filled="2", cost="30", fees=[{"currency": "USDC", "cost": "0.3"}]
    )
    await _persist(order, "sell-1")
    await _persist(order, "sell-1")
    report = await accumulation_performance(adapter)
    group = report["by_quote"][0]
    assert report["complete"]
    assert Decimal(group["market_value"]) == 96
    assert Decimal(group["realized"]) == Decimal("9.5")
    assert Decimal(group["unrealized"]) == Decimal("15.2")
    assert Decimal(group["total_return"]) == Decimal("24.7")
    assert report["history_complete"]
    assert sum(Decimal(row["profit"]) for row in report["realized_by_date"]) == Decimal(
        "9.5"
    )


@pytest.mark.asyncio
async def test_closed_native_performance_survives_holding_deletion(accounting_db):
    activation, _, _ = await _buy()
    await _persist(_order(fees=[{"currency": "USDC", "cost": "1"}]))
    await _complete()
    await _sell(activation, action="close")
    await _persist(
        _order(
            side="sell",
            filled="10",
            cost="120",
            fees=[{"currency": "USDC", "cost": "1"}],
        ),
        "sell-1",
    )
    adapter = _performance_adapter()
    report = await accumulation_performance(adapter)
    assert report["complete"] and Decimal(report["by_quote"][0]["realized"]) == 18
    assert report["by_quote"][0]["market_value"] == "0"
    assert report["history_complete"]
    assert sum(Decimal(row["profit"]) for row in report["realized_by_date"]) == 18
    adapter.mark_quotes.assert_not_awaited()


@pytest.mark.asyncio
async def test_statistics_combines_verified_native_returns_without_double_counting_cost(
    accounting_db, monkeypatch
):
    from service.statistic import Statistic

    await _buy()
    await _persist(_order(fees=[{"currency": "USDC", "cost": "1"}]))
    adapter = _performance_adapter()
    report = await accumulation_performance(adapter)
    adapter.config_provider = lambda: {"currency": "USDC"}
    owner = SimpleNamespace(
        ready=True, adapter=adapter, performance=AsyncMock(return_value=report)
    )
    monkeypatch.setattr(
        "service.runtime_services.get_active_accumulation_runtime", lambda: owner
    )
    statistic = Statistic()
    monkeypatch.setattr(statistic, "_get_sum_value", AsyncMock(return_value=3))
    monkeypatch.setattr(statistic, "_get_profit_rows_since", AsyncMock(return_value=[]))
    monkeypatch.setattr(statistic, "_store_upnl_snapshot", AsyncMock())
    await statistic.invalidate_profit_caches()
    result = await statistic._get_profit_base_cached()
    assert (
        result["performance_complete"] and result["performance_scope"] == "all_trades"
    )
    assert result["upnl"] == 19 and result["profit_overall"] == 22
    assert result["funds_locked"] == 101


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "issue",
    [
        "missing_mark",
        "stale",
        "future",
        "foreign_account",
        "unknown_fees",
        "external_fee",
        "adjusted",
        "missing_link",
        "deleted_inventory",
        "ledger_race",
    ],
)
async def test_incomplete_performance_never_fabricates_net_profit(accounting_db, issue):
    activation, _, _ = await _buy()
    fees = (
        []
        if issue == "unknown_fees"
        else [{"currency": "BNB" if issue == "external_fee" else "USDC", "cost": "1"}]
    )
    await _persist(_order(fees=fees))
    adapter = _performance_adapter()
    if issue == "missing_mark":
        adapter.mark_quotes.return_value = {}
    elif issue == "stale":
        adapter.mark_quotes.return_value["BTC/USDC"]["observed_at_ms"] = -10000
    elif issue == "future":
        adapter.mark_quotes.return_value["BTC/USDC"]["observed_at_ms"] = 1001
    elif issue == "foreign_account":
        adapter.account_scope.return_value = "other"
    elif issue == "adjusted":
        await model.OpenTrades.all().update(
            execution_history_complete=False,
            accumulation_basis_provenance="operator_adjusted",
        )
    elif issue == "missing_link":
        await model.AccumulationActivation.all().update(holding_id=None)
    elif issue == "deleted_inventory":
        await model.OpenTrades.all().delete()
    elif issue == "ledger_race":

        async def mark(*args):
            await model.OpenTrades.all().update(accumulation_net_quantity="9")
            return {"BTC/USDC": {"bid": "12", "observed_at_ms": 1000}}

        adapter.mark_quotes.side_effect = mark
    report = await accumulation_performance(adapter)
    assert not report["complete"]
    group = report["by_quote"][0]
    assert group["total_return"] is None
    if issue in {"missing_mark", "stale", "future", "foreign_account"}:
        assert Decimal(group["realized"]) == 0
    else:
        assert group["realized"] is None
    if issue in {
        "missing_mark",
        "stale",
        "future",
        "foreign_account",
        "missing_link",
        "deleted_inventory",
        "ledger_race",
    }:
        assert group["market_value"] is None


@pytest.mark.asyncio
async def test_cumulative_partial_fills_and_duplicate_fees_are_counted_once(
    accounting_db,
):
    activation, opportunity, placement = await _buy()
    first = _order(
        filled="4", cost="40", status="open", fees=[{"currency": "BTC", "cost": "0.04"}]
    )
    first["fee"] = {"currency": "BTC", "cost": "0.04"}
    result = await _persist(first)
    assert not result.settled and result.consumed
    assert result.inventory["quantity"] == "3.96"
    assert await _persist(first) == result
    await opportunity.refresh_from_db()
    assert (
        opportunity.unresolved_slot == activation.id
        and opportunity.consumption_revision == 1
    )
    second = _order(
        fees=[{"currency": "BTC", "cost": "0.1"}, {"currency": "USDC", "cost": "1"}]
    )
    settled = await _persist(second)
    assert settled.settled
    assert Decimal(settled.inventory["quantity"]) == Decimal("9.9")
    assert Decimal(settled.inventory["remaining_cost"]) == 101
    assert Decimal(settled.inventory["contributed_quote"]) == 100
    await opportunity.refresh_from_db()
    await activation.refresh_from_db()
    await placement.refresh_from_db()
    assert opportunity.unresolved_slot is None and opportunity.status == "consumed"
    assert activation.consumption_revision == 1
    assert json.loads(activation.execution_guard_json)["signal_price"] == "97"
    assert placement.state == "persisted" and placement.reserved_quote == 1000
    assert await model.TradeExecutions.all().count() == 2
    await _complete()
    assert await _persist({**second, "timestamp": 3000}) == settled
    equivalent = {
        **second,
        "filled": 10.0,
        "cost": "100.00",
        "fees": [
            {"currency": "BTC", "cost": "0.1000"},
            {"currency": "USDC", "cost": 1.0},
            {"currency": "BNB", "cost": "0"},
        ],
    }
    assert await _persist(equivalent) == settled
    assert await model.TradeExecutions.all().count() == 2


@pytest.mark.asyncio
async def test_concurrent_duplicate_and_restart_recovery_are_idempotent(accounting_db):
    await _buy()
    one, two = await asyncio.gather(_persist(_order()), _persist(_order()))
    assert one == two
    await Tortoise.close_connections()
    await Tortoise.init(db_url=accounting_db, modules={"models": ["model"]})
    assert await _persist(_order()) == one
    assert await model.TradeExecutions.all().count() == 1


@pytest.mark.asyncio
async def test_failed_checkpoint_rolls_back_inventory_ledger_and_consumption(
    accounting_db, monkeypatch
):
    activation, opportunity, placement = await _buy()
    notification = Mock()
    monkeypatch.setattr(
        "service.accumulation_accounting.accumulation_input_notifications.publish",
        notification,
    )
    monkeypatch.setattr(
        model.AccumulationFillCheckpoint,
        "update_or_create",
        AsyncMock(side_effect=OperationalError("disk failure")),
    )
    with pytest.raises(OperationalError):
        await _persist(_order())
    assert await model.OpenTrades.all().count() == 0
    assert await model.TradeExecutions.all().count() == 0
    await activation.refresh_from_db()
    await opportunity.refresh_from_db()
    await placement.refresh_from_db()
    assert activation.consumption_revision == 0 and activation.holding_id is None
    assert (
        opportunity.consumed_at is None and opportunity.unresolved_slot == activation.id
    )
    assert placement.state == "accepted"
    notification.assert_not_called()


@pytest.mark.asyncio
async def test_committed_fill_emits_only_a_shared_input_hint(
    accounting_db, monkeypatch
):
    await _buy()
    notification = Mock()
    monkeypatch.setattr(
        "service.accumulation_accounting.accumulation_input_notifications.publish",
        notification,
    )
    await _persist(_order())
    notification.assert_called_once_with()
    assert await model.OpenTrades.all().count() == 1
    assert await model.AccumulationFillCheckpoint.all().count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("retained_fills", [10, 1000, 100000])
async def test_routine_reporting_rows_stay_bounded_with_long_execution_history(
    accounting_db, monkeypatch, retained_fills
):
    from service.capital_budget import CapitalBudgetService
    from service.database import Database

    activation, _, _ = await _buy()
    await _persist(
        _order(filled="20", cost="200", fees=[{"currency": "USDC", "cost": "1"}])
    )
    await _complete()
    await _sell(activation, quantity="10")
    await _persist(
        _order(
            side="sell",
            filled="10",
            cost="120",
            fees=[{"currency": "USDC", "cost": "1"}],
        ),
        "sell-1",
    )
    source = await model.TradeExecutions.get(role="accumulation_sell")
    await source.delete()
    with localcontext() as context:
        context.prec = 512
        count = Decimal(retained_fills)
        delta = {
            "filled": str(Decimal("10") / count),
            "quote_cost": str(Decimal("120") / count),
            "fees": {"USDC": str(Decimal("1") / count)},
            "allocated_basis": str(Decimal("100.5") / count),
        }
    for start in range(0, retained_fills, 1000):
        await model.TradeExecutions.bulk_create(
            [
                model.TradeExecutions(
                    deal_id=source.deal_id,
                    symbol=source.symbol,
                    side="sell",
                    role="accumulation_sell",
                    timestamp=source.timestamp,
                    price=12,
                    amount=float(delta["filled"]),
                    ordersize=float(delta["quote_cost"]),
                    metadata_json=json.dumps({"accumulation": {"delta": delta}}),
                )
                for _ in range(start, min(start + 1000, retained_fills))
            ]
        )
    checkpoint = await model.AccumulationFillCheckpoint.get(
        placement__operation_id="sell-1"
    )
    # Retain the same number of settled, zero-fill attempts as a second pressure
    # source. They change no economics but must not become a lifetime row scan.
    for start in range(0, retained_fills, 1000):
        ids = [
            f"historical-zero-{index}"
            for index in range(start, min(start + 1000, retained_fills))
        ]
        await model.PlacementIntent.bulk_create(
            [
                model.PlacementIntent(
                    operation_id=value,
                    symbol="BTC/USDC",
                    exchange_name="binance",
                    action="buy",
                    side="buy",
                    order_type="limit",
                    state="completed",
                )
                for value in ids
            ]
        )
        placements = await model.PlacementIntent.filter(
            operation_id__in=ids
        ).values_list("id", flat=True)
        await model.AccumulationFillCheckpoint.bulk_create(
            [
                model.AccumulationFillCheckpoint(
                    placement_id=placement,
                    activation=activation,
                    deal_id=source.deal_id,
                    filled="0",
                    quote_cost="0",
                    fees_json="{}",
                    fees_complete=True,
                    terminal=True,
                    evidence_json="{}",
                    inventory_json=checkpoint.inventory_json,
                )
                for placement in placements
            ]
        )
    await Database()._ensure_accumulation_return_schema()
    adapter = _performance_adapter()
    before = await accumulation_performance(adapter)
    group = before["by_quote"][0]
    assert before["complete"] and before["history_complete"]
    assert Decimal(group["realized"]) == Decimal("18.5")
    assert Decimal(group["unrealized"]) == Decimal("19.5")
    assert Decimal(group["total_return"]) == 38
    # A portable restore drops derived projections, never audit history.
    await model.AccumulationReturnTotals.all().delete()
    await model.AccumulationReturnDay.all().delete()
    rebuilt = await accumulation_performance(adapter)
    assert rebuilt["by_quote"] == before["by_quote"]
    assert rebuilt["realized_by_date"] == before["realized_by_date"]
    assert rebuilt["history_complete"]
    connection = Tortoise.get_connection("default")
    original = connection.execute_query
    returned = []

    async def record(sql, *args, **kwargs):
        result = await original(sql, *args, **kwargs)
        if sql.lstrip().upper().startswith("SELECT"):
            returned.append((sql, len(result[1])))
        return result

    monkeypatch.setattr(connection, "execute_query", record)
    report = await accumulation_performance(adapter)
    await CapitalBudgetService()._load_usage(
        {"capital_max_fund": 1000, "bo": 10, "so": 10, "mstc": 0}
    )
    assert report["by_quote"] == before["by_quote"]
    assert max(size for _, size in returned) <= 10
    assert not any('FROM "tradeexecutions"' in sql for sql, _ in returned)


@pytest.mark.asyncio
async def test_terminal_unknown_fees_remain_committed_then_apply_late_fee_once(
    accounting_db,
):
    activation, opportunity, placement = await _buy()
    unknown = await _persist(_order(fees=[]))
    assert not unknown.settled and unknown.inventory["pending_fee_reports"] == 1
    await opportunity.refresh_from_db()
    assert opportunity.unresolved_slot == activation.id
    known = await _persist(_order(fees=[{"currency": "BTC", "cost": "0.1"}]))
    assert known.settled and known.inventory["pending_fee_reports"] == 0
    assert known.inventory["quantity"] == "9.9"
    assert await _persist(_order(fees=[{"currency": "BTC", "cost": "0.1"}])) == known
    await activation.refresh_from_db()
    assert activation.consumption_revision == 1
    assert await model.TradeExecutions.all().count() == 2


@pytest.mark.asyncio
async def test_partial_sale_allocates_basis_and_keeps_gross_contribution(accounting_db):
    activation, _, _ = await _buy()
    await _persist(_order(fees=[{"currency": "USDC", "cost": "1"}]))
    await _complete()
    await _sell(activation)
    sold = await _persist(
        _order(
            side="sell",
            filled="2",
            cost="30",
            fees=[{"currency": "USDC", "cost": "0.3"}],
        ),
        "sell-1",
    )
    assert Decimal(sold.inventory["quantity"]) == 8
    assert Decimal(sold.inventory["remaining_cost"]) == Decimal("80.8")
    assert Decimal(sold.inventory["contributed_quote"]) == 100
    assert Decimal(sold.inventory["disposal_proceeds"]) == Decimal("29.7")
    await _complete("sell-1")
    result = await AccumulationLifecycleService().complete_settlement(
        "manual-1", account_scope="account-1"
    )
    assert result.state == "enabled"
    ledger = await model.TradeExecutions.filter(side="sell").get()
    assert Decimal(
        json.loads(ledger.metadata_json)["accumulation"]["delta"]["allocated_basis"]
    ) == Decimal("20.2")


@pytest.mark.asyncio
async def test_full_close_partial_fill_keeps_closing_then_archives_exact_totals(
    accounting_db,
):
    activation, _, _ = await _buy()
    await _persist(_order())
    await _complete()
    await _sell(activation, action="close")
    await _persist(_order(side="sell", filled="4", cost="44", status="open"), "sell-1")
    await activation.refresh_from_db()
    assert activation.state == "closing"
    assert (
        await model.OpenTrades.get(id=activation.holding_id)
    ).accumulation_net_quantity == "6"
    await _persist(_order(side="sell", filled="10", cost="110"), "sell-1")
    assert await model.OpenTrades.all().count() == 0
    await _complete("sell-1")
    result = await AccumulationLifecycleService().complete_settlement(
        "manual-1", account_scope="account-1"
    )
    assert result.state == "stopped"
    checkpoint = await model.AccumulationFillCheckpoint.get(
        placement__operation_id="sell-1"
    )
    totals = json.loads(checkpoint.inventory_json)
    assert (
        Decimal(totals["quantity"]) == 0 and Decimal(totals["disposal_proceeds"]) == 110
    )
    assert await model.TradeExecutions.all().count() == 3
    await Tortoise.close_connections()
    await Tortoise.init(db_url=accounting_db, modules={"models": ["model"]})
    assert (await model.AccumulationActivation.get(id=activation.id)).state == "stopped"
    from service.accumulation_status import get_accumulation_status

    status = await get_accumulation_status("BTC/USDC", wait_reasons={})
    assert status["holding"] is None
    assert status["portfolio"]["holding_count"] == 0
    assert len(status["orders"]) == 2
    assert status["orders"][0]["side"] == "sell"
    assert status["orders"][0]["filled_quantity"] == "10"
    assert status["orders"][0]["inventory_at_update"]["net_quantity"] == "0"
    assert status["orders"][0]["inventory_at_update"]["disposal_proceeds"] == "110"


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_terminal_zero_fill_releases_slot_without_consuming(
    accounting_db, expired
):
    activation, opportunity, _ = await _buy()
    if expired:
        opportunity.expires_at_ms = 1
        await opportunity.save()
    result = await _persist(_order(filled="0", cost="0", status="canceled"))
    await opportunity.refresh_from_db()
    await activation.refresh_from_db()
    assert result.settled and not result.consumed and result.inventory is None
    assert opportunity.status == ("expired" if expired else "retryable")
    assert opportunity.unresolved_slot is None and opportunity.retry_index == 1
    assert opportunity.next_retry_at is not None
    assert (
        activation.consumption_revision == 0 and activation.execution_guard_json is None
    )
    assert await model.OpenTrades.all().count() == 0


@pytest.mark.asyncio
async def test_late_fill_after_expiry_and_pause_is_accounted(accounting_db):
    activation, opportunity, _ = await _buy()
    opportunity.expires_at_ms = 1
    await opportunity.save()
    pause = await AccumulationLifecycleService().submit(
        {
            "symbol": "BTC/USDC",
            "operation_id": "pause",
            "action": "pause",
            "expected_revision": 0,
        },
        account_scope="account-1",
    )
    assert pause.status == "pending"
    await _persist(_order(filled="2", cost="20", status="canceled"))
    await _complete()
    result = await AccumulationLifecycleService().complete_settlement(
        "pause", account_scope="account-1"
    )
    assert result.state == "paused"
    await opportunity.refresh_from_db()
    assert opportunity.status == "consumed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    ["order", "scope", "decrease", "unbound", "oversell", "missing_incremental_cost"],
)
async def test_invalid_evidence_or_ownership_never_changes_inventory(
    accounting_db, mutation
):
    activation, _, placement = await _buy()
    await _persist(_order(filled="4", cost="40", status="open"))
    report = _order(filled="5", cost="50", status="open")
    scope = "account-1"
    if mutation == "order":
        report["id"] = "other"
    if mutation == "scope":
        scope = "other"
    if mutation == "decrease":
        report["filled"] = "3"
    if mutation == "missing_incremental_cost":
        report["cost"] = "40"
    if mutation == "unbound":
        await model.AccumulationAttempt.filter(placement=placement).delete()
    if mutation == "oversell":
        await _persist(_order(filled="4", cost="40"))
        await _complete()
        await _sell(activation)
        placement = await model.PlacementIntent.get(operation_id="sell-1")
        report = _order(side="sell", filled="5", cost="50")
    with pytest.raises(AccumulationStateError):
        await persist_accumulation_order(
            placement.operation_id, report, account_scope=scope, exchange_name="binance"
        )
    assert (
        await model.OpenTrades.get(symbol="BTC/USDC")
    ).accumulation_net_quantity == "4"


@pytest.mark.asyncio
async def test_recovery_keeps_unknown_order_committed_and_handles_canceled_partial_sell(
    accounting_db,
):
    activation, _, _ = await _buy()
    await _persist(_order())
    await _complete()
    placement = await _sell(activation, action="close")
    exchange = SimpleNamespace(
        lookup_spot_order=AsyncMock(
            return_value=ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.UNAVAILABLE
            )
        )
    )
    recovery = AccumulationPlacementRecovery(
        exchange, AsyncMock(return_value="account-1")
    )
    legacy = AsyncMock(side_effect=AssertionError("DCA finalizer must not run"))
    reconciler = PlacementReconciler(
        exchange, legacy, accumulation_recovery=recovery.reconcile
    )
    config = {"exchange": "binance", "market": "spot", "dry_run": False}
    assert not (await reconciler.reconcile(config)).ready
    await placement.refresh_from_db()
    assert placement.state == "accepted"
    exchange.lookup_spot_order.return_value = ExchangeOrderLookupResult(
        status=ExchangeOrderLookupStatus.FOUND,
        order=_order(side="sell", filled="2", cost="22", status="canceled"),
    )
    assert (await reconciler.reconcile(config)).ready
    await placement.refresh_from_db()
    assert placement.state == "completed"
    assert (
        await model.OpenTrades.get(symbol="BTC/USDC")
    ).accumulation_net_quantity == "8"
    await activation.refresh_from_db()
    assert activation.state == "closing"
    legacy.assert_not_called()


@pytest.mark.asyncio
async def test_default_recovery_quarantines_accumulation_without_exchange_access(
    accounting_db,
):
    _, _, placement = await _buy()
    exchange = SimpleNamespace(
        lookup_spot_order=AsyncMock(side_effect=AssertionError("no lookup"))
    )
    legacy = AsyncMock(side_effect=AssertionError("no DCA persistence"))
    result = await PlacementReconciler(exchange, legacy).reconcile({})
    await placement.refresh_from_db()
    assert not result.ready and placement.state == "quarantined"
    exchange.lookup_spot_order.assert_not_called()
    legacy.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_acceptance_recovers_by_client_identity(accounting_db):
    activation, opportunity, placement = await _buy()
    placement.state = "indeterminate"
    placement.exchange_order_id = None
    placement.client_order_id = "client-buy-1"
    await placement.save()
    evidence = {**_order(), "clientOrderId": "wrong-client"}
    with pytest.raises(AccumulationStateError, match="client identity"):
        await _persist(evidence)
    evidence["clientOrderId"] = "client-buy-1"
    assert (await _persist(evidence)).settled
    await placement.refresh_from_db()
    assert placement.exchange_order_id == "exchange-buy-1"
    await activation.refresh_from_db()
    assert activation.consumption_revision == 1


@pytest.mark.asyncio
async def test_prepared_recovery_releases_only_a_proven_unsubmitted_attempt(
    accounting_db,
):
    activation, opportunity, placement = await _buy()
    placement.state = "prepared"
    placement.exchange_order_id = None
    await placement.save()
    exchange = SimpleNamespace(
        lookup_spot_order=AsyncMock(side_effect=AssertionError("no lookup"))
    )
    recovery = AccumulationPlacementRecovery(
        exchange, AsyncMock(return_value="account-1")
    )
    reconciler = PlacementReconciler(
        exchange, AsyncMock(), accumulation_recovery=recovery.reconcile
    )
    summary = await reconciler.reconcile(
        {"exchange": "binance", "market": "spot", "dry_run": False}
    )
    assert summary.ready and summary.rejected == 1
    await opportunity.refresh_from_db()
    assert opportunity.unresolved_slot is None and opportunity.consumed_at is None
    assert await model.TradeExecutions.all().count() == 0


@pytest.mark.asyncio
async def test_recovery_account_mismatch_blocks_lookup_and_inventory_mutation(
    accounting_db,
):
    await _buy()
    exchange = SimpleNamespace(
        lookup_spot_order=AsyncMock(side_effect=AssertionError("no lookup"))
    )
    recovery = AccumulationPlacementRecovery(
        exchange, AsyncMock(return_value="other-account")
    )
    summary = await PlacementReconciler(
        exchange, AsyncMock(), accumulation_recovery=recovery.reconcile
    ).reconcile({"exchange": "binance", "market": "spot", "dry_run": False})
    assert not summary.ready and summary.quarantined == 1
    assert await model.OpenTrades.all().count() == 0
    exchange.lookup_spot_order.assert_not_called()


@pytest.mark.asyncio
async def test_manual_sale_context_is_preserved_and_part_of_placement_retry_identity(
    accounting_db,
):
    intents = PlacementIntentService()
    order = {
        "operation_id": "manual-context",
        "symbol": "BTC/USDC",
        "total_amount": 1,
        "accumulation_operation_id": "close-1",
        "accumulation_action": "close",
    }
    config = {"exchange": "binance", "market": "spot", "dry_run": False}
    args = dict(action="sell", side="sell", order_type="market", requested_amount=1)
    prepared = await intents.prepare(order, config, **args)
    stored = json.loads(prepared.intent.request_json)
    assert stored["accumulation_operation_id"] == "close-1"
    assert stored["accumulation_action"] == "close"
    with pytest.raises(ValueError, match="different request"):
        await intents.prepare(
            {**order, "accumulation_action": "sell_partial"}, config, **args
        )


def test_base_sell_fee_and_unknown_imported_basis_remain_explicit():
    inventory = AccumulationInventory(
        "10", None, None, "0", {}, basis_provenance="unknown"
    )
    report = AccumulationFill.from_order(
        _order(
            side="sell",
            filled="2",
            cost="30",
            fees=[{"currency": "BTC", "cost": "0.1"}],
        )
    )
    result, delta = apply_fill_delta(inventory, report)
    assert result.quantity == "7.9" and result.remaining_cost is None
    assert result.contributed_quote is None and delta["allocated_basis"] is None
    valued, delta = apply_fill_delta(
        replace(inventory, remaining_cost="100", contributed_quote="100"), report
    )
    assert Decimal(valued.remaining_cost) == 79


def test_third_currency_fee_preserves_units_without_inventing_quote_value():
    report = AccumulationFill.from_order(
        _order(fees=[{"currency": "BNB", "cost": "0.01"}])
    )
    result, _ = apply_fill_delta(AccumulationInventory("0", "0", "0", "0", {}), report)
    assert result.basis_provenance == "unvalued_external_fees"
    assert result.fees == {"BNB": "0.01"} and result.remaining_cost == "100"


@pytest.mark.parametrize(
    "changes",
    [
        {"filled": float("nan")},
        {"filled": True},
        {"cost": None},
        {"status": "unknown"},
        {"timestamp": True},
        {"fees": [{"currency": "BTC", "cost": "-1"}]},
    ],
)
def test_normalizer_rejects_incomplete_or_invalid_evidence(changes):
    with pytest.raises(AccumulationStateError):
        AccumulationFill.from_order({**_order(), **changes})


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_client", [False, True])
async def test_native_missing_ids_can_be_repaired_under_rotated_credentials_only_with_signed_client_proof(
    accounting_db, wrong_client
):
    from service.accumulation_repair import AccumulationOrderRepair
    from service.exchange_capabilities import build_client_order_id

    activation, _, placement = await _buy()
    placement.operation_id = "buy-" + "a" * 32
    placement.client_order_id = None
    placement.exchange_order_id = None
    placement.result_json = None
    await placement.save()
    request = await _quarantine(activation, placement)
    order = _order()
    order["clientOrderId"] = (
        "wrong-native-client"
        if wrong_client
        else build_client_order_id(placement.operation_id)
    )
    adapter = _repair_adapter(order)
    adapter.account_scope.return_value = "rotated-account"
    if wrong_client:
        with pytest.raises((AccumulationConflictError, AccumulationStateError)):
            await AccumulationOrderRepair(adapter).submit(request)
        await activation.refresh_from_db()
        assert activation.account_scope == "account-1"
        assert await model.TradeExecutions.all().count() == 0
    else:
        result = await AccumulationOrderRepair(adapter).submit(request)
        assert result.status == "applied"
        await activation.refresh_from_db()
        await placement.refresh_from_db()
        assert (
            activation.account_scope == "rotated-account"
            and activation.explicitly_paused
        )
        assert placement.client_order_id == order["clientOrderId"]
        assert await model.TradeExecutions.all().count() == 1
        assert await AccumulationOrderRepair(adapter).submit(request) == result
        adapter.exchange.lookup_spot_order.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("registrations", [1, 25])
async def test_checkpoint_summary_batches_flags_and_exact_latest_order(
    accounting_db, monkeypatch, registrations
):
    from service.accumulation_performance import _checkpoint_summaries

    owner, _, _ = await _buy()
    owners = [owner]
    for index in range(1, registrations):
        owners.append(
            await model.AccumulationActivation.create(
                symbol=f"COIN{index}/USDC",
                account_scope="account-1",
                state="stopped",
                strategy_version_id=owner.strategy_version_id,
            )
        )
    stamp = datetime.now(timezone.utc)
    for index, activation in enumerate(owners):
        for attempt in range(2):
            placement = await model.PlacementIntent.create(
                operation_id=f"summary-{index}-{attempt}",
                symbol=activation.symbol,
                exchange_name="binance",
                side="buy",
                action="buy",
                order_type="limit",
                state="completed",
            )
            checkpoint = await model.AccumulationFillCheckpoint.create(
                activation=activation,
                placement=placement,
                inventory_json=json.dumps({"attempt": attempt}),
                deal_id=f"deal-{attempt}",
                fees_complete=attempt == 1,
                terminal=attempt == 1,
                evidence_json="{}",
            )
            await model.AccumulationFillCheckpoint.filter(id=checkpoint.id).update(
                updated_at=stamp
            )
    conn = Tortoise.get_connection("default")
    execute = conn.execute_query_dict
    queries = []

    async def capture(query, *args, **kwargs):
        queries.append(query)
        return await execute(query, *args, **kwargs)

    monkeypatch.setattr(conn, "execute_query_dict", capture)
    summaries = await _checkpoint_summaries(conn)
    assert len(queries) == 1
    assert len(summaries) == registrations
    for activation in owners:
        latest = (
            await model.AccumulationFillCheckpoint.filter(activation=activation)
            .order_by("-updated_at", "-id")
            .first()
        )
        summary = summaries[str(activation.id)]
        assert summary["deal_id"] == latest.deal_id == "deal-1"
        assert summary["inventory_json"] == latest.inventory_json
        assert summary["incomplete_fees"] == 1
        assert summary["unsettled"] == 1
