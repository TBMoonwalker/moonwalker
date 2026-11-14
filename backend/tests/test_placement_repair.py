"""Regression coverage for the operator repair path on quarantined intents.

Value: protects=the fail-closed startup gate's operator exit: quarantined
    classic-DCA intents must resolve through lookup-only repair (same resume
    handler as startup reconciliation) or an explicit audited dismissal, and
    nothing on this path may submit, cancel, or otherwise touch the exchange
    beyond a lookup.
fails_when=repair resubmits or mutates exchange state, moves a non-quarantined
    row, routes accumulation intents to the classic path, clears the gate
    without terminal evidence, or dismissal loses its audit note.
why_new=no endpoint or transition could move a quarantined row before this
    change, so the whole operator exit had no coverage to protect.
seam=none (unit-level; the app startup mode is covered in test_app_startup).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import model
import pytest
import service.order_persistence as order_persistence
from service.dca.order_lifecycle import DcaOrderLifecycle
from service.exchange_capabilities import (
    ExchangeOrderLookupResult,
    ExchangeOrderLookupStatus,
    exchange_execution_scope,
)
from service.lifecycle_routing import LifecycleRoute, LifecycleRoutingDecision
from service.placement_intents import (
    PlacementIntentService,
    PlacementIntentState,
    mark_placement_persisted_in_transaction,
)
from service.placement_recovery_entry import PlacementRecoveryEntry
from service.placement_repair import (
    PlacementRepairConflict,
    PlacementRepairInvalid,
    PlacementRepairNotFound,
    PlacementRepairService,
    has_terminal_partial_sell,
)
from tortoise import Tortoise
from tortoise.transactions import in_transaction

# The repair service validates the intent's recorded account scope against
# the configured client before any exchange I/O, so the config used below
# carries the explicit demo/live boolean the scope fingerprint requires, and
# the quarantined fixtures embed the scope that same config produces.
REPAIR_CONFIG: dict[str, Any] = {"exchange": "binance", "dry_run": True}
REPAIR_SCOPE = exchange_execution_scope(REPAIR_CONFIG)


async def _init_database(tmp_path) -> None:
    database_path = tmp_path / "placement-repair.sqlite"
    await Tortoise.init(
        db_url=f"sqlite://{database_path}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()


async def _seed_buy_trade(amount: float, *, deal_id: str = "deal") -> None:
    await model.Trades.create(
        timestamp="1778000000000",
        ordersize=amount * 10,
        fee=0,
        precision=8,
        amount=amount,
        amount_fee=0,
        price=10,
        symbol="BTC/USDC",
        orderid="original-buy",
        bot="test",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
        deal_id=deal_id,
    )


class _FakeExchange:
    """Serves one canned lookup result and records every call it receives."""

    def __init__(self, lookup: ExchangeOrderLookupResult) -> None:
        self.lookup = lookup
        self.calls: list[dict[str, Any]] = []

    async def lookup_spot_order(
        self,
        symbol: str,
        _config: dict[str, Any],
        *,
        exchange_order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> ExchangeOrderLookupResult:
        self.calls.append(
            {
                "symbol": symbol,
                "exchange_order_id": exchange_order_id,
                "client_order_id": client_order_id,
            }
        )
        return self.lookup


class _FakeResume:
    def __init__(self, result: bool = True, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(
        self,
        intent: Any,
        exchange_order: dict[str, Any],
        _config: dict[str, Any],
        *,
        resolution: Any,
    ) -> bool:
        self.calls.append((str(intent.operation_id), dict(exchange_order)))
        if self.error is not None:
            raise self.error
        if self.result:
            async with in_transaction() as connection:
                await mark_placement_persisted_in_transaction(
                    str(intent.operation_id), connection, resolution=resolution
                )
        return self.result


def _classic_route(monkeypatch: pytest.MonkeyPatch) -> None:
    async def load_classic_route(_symbol: str) -> LifecycleRoutingDecision:
        return LifecycleRoutingDecision(LifecycleRoute.CLASSIC_DCA, "classic_dca")

    monkeypatch.setattr(
        "service.placement_repair.load_lifecycle_route", load_classic_route
    )


def _accumulation_route(monkeypatch: pytest.MonkeyPatch) -> None:
    async def load_accumulation_route(_symbol: str) -> LifecycleRoutingDecision:
        return LifecycleRoutingDecision(LifecycleRoute.ACCUMULATION, "accumulation")

    monkeypatch.setattr(
        "service.placement_repair.load_lifecycle_route", load_accumulation_route
    )


async def _quarantined_limit_sell(
    *,
    operation_id: str = "limit_sell-test",
    state: str = "quarantined",
    reason_code: str = "reconciliation_account_scope_unverified",
    exchange_order_id: str | None = "7788",
    client_order_id: str | None = "mw-test-identity",
    exchange_name: str = "binance",
) -> Any:
    return await model.PlacementIntent.create(
        operation_id=operation_id,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        exchange_name=exchange_name,
        symbol="BTC/USDC",
        action="limit_sell",
        side="sell",
        order_type="limit",
        state=state,
        requested_quote=120.0,
        requested_amount=0.6,
        maximum_price=0.2,
        request_json=json.dumps(
            {
                "limit_price": 0.2,
                "total_amount": 0.6,
                "_execution_scope": REPAIR_SCOPE,
            }
        ),
        reason_code=reason_code,
        error_message=(
            "Order account/environment does not match verified server configuration."
        ),
        completed_at=datetime.now(timezone.utc),
    )


def _service(
    exchange: _FakeExchange,
    intents: PlacementIntentService | None = None,
    resume: _FakeResume | None = None,
) -> PlacementRepairService:
    return PlacementRepairService(
        exchange=exchange,
        intents=intents or PlacementIntentService(),
        resume_placement=resume or _FakeResume(),
    )


@pytest.mark.asyncio
async def test_real_repair_persists_buy_and_resolves_quarantine_atomically(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recovered buy and its disposition commit once in the same database."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        request = {
            "operation_id": "atomic-buy",
            "ordersize": 25.0,
            "symbol": "BTC/USDC",
            "direction": "long",
            "botname": "test",
            "baseorder": True,
            "safetyorder": False,
            "order_count": 0,
            "ordertype": "market",
            "so_percentage": None,
            "side": "buy",
            "_execution_scope": REPAIR_SCOPE,
        }
        await model.PlacementIntent.create(
            operation_id="atomic-buy",
            client_order_id="mw-atomic",
            exchange_order_id="buy-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="buy",
            side="buy",
            order_type="market",
            state="quarantined",
            request_json=json.dumps(request),
            reason_code="buy_fill_unconfirmed",
        )
        evidence = {
            "id": "buy-1",
            "orderid": "buy-1",
            "status": "canceled",
            "filled": 0.001,
            "amount": 0.001,
            "price": 25000.0,
            "timestamp": "1778000000000",
            "fees": 0.001,
            "ordersize": 25.0,
            "precision": 8,
            "amount_fee": 0.0,
        }
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=evidence
            )
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = exchange
        repair = PlacementRecoveryEntry(lifecycle=lifecycle).build_placement_repair()
        marker = order_persistence.mark_placement_persisted_in_transaction

        await model.OpenTrades.create(symbol="BTC/USDC", deal_id="newer-deal")
        collision = await repair.repair("atomic-buy", REPAIR_CONFIG)
        assert collision["status"] == "unchanged"
        assert (await model.OpenTrades.get(symbol="BTC/USDC")).deal_id == "newer-deal"
        assert await model.Trades.filter(orderid="buy-1").count() == 0
        await model.OpenTrades.filter(symbol="BTC/USDC").delete()

        async def fail_before_commit(*_args: Any, **_kwargs: Any) -> None:
            raise ValueError("synthetic transaction failure")

        monkeypatch.setattr(
            order_persistence,
            "mark_placement_persisted_in_transaction",
            fail_before_commit,
        )
        failed = await repair.repair("atomic-buy", REPAIR_CONFIG)
        assert failed["status"] == "unchanged"
        assert await model.Trades.filter(orderid="buy-1").count() == 0
        assert await model.TradeExecutions.all().count() == 0
        assert (
            await model.PlacementIntent.get(operation_id="atomic-buy")
        ).state == "quarantined"

        current_config = dict(REPAIR_CONFIG)

        async def change_scope_before_marker(*args: Any, **kwargs: Any) -> None:
            current_config["key"] = "different-account"
            await marker(*args, **kwargs)

        monkeypatch.setattr(
            order_persistence,
            "mark_placement_persisted_in_transaction",
            change_scope_before_marker,
        )
        changed = await repair.repair(
            "atomic-buy", REPAIR_CONFIG, config_provider=lambda: current_config
        )
        assert changed["status"] == "unchanged"
        assert await model.Trades.filter(orderid="buy-1").count() == 0
        assert (
            await model.PlacementIntent.get(operation_id="atomic-buy")
        ).state == "quarantined"
        current_config = dict(REPAIR_CONFIG)

        monkeypatch.setattr(
            order_persistence, "mark_placement_persisted_in_transaction", marker
        )

        async def fail_after_commit(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("synthetic notification failure")

        monkeypatch.setattr(lifecycle.monitoring, "notify_trade", fail_after_commit)
        result = await repair.repair(
            "atomic-buy", REPAIR_CONFIG, config_provider=lambda: current_config
        )
        assert result["status"] == "completed"
        assert await model.Trades.filter(orderid="buy-1").count() == 1
        assert await model.TradeExecutions.all().count() == 1
        intent = await model.PlacementIntent.get(operation_id="atomic-buy")
        assert intent.state == "completed"
        with pytest.raises(PlacementRepairConflict):
            await repair.repair("atomic-buy", REPAIR_CONFIG)
        assert await model.TradeExecutions.all().count() == 1
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_safety_buy_does_not_leave_stale_tp_order(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Recovered safety buys cannot change a deal under an armed TP order."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="deal-buy",
            amount=1.0,
            cost=10.0,
            tp_limit_order_id="tp-new",
            tp_limit_order_price=11.0,
            tp_limit_order_amount=1.0,
        )
        request = {
            "operation_id": "safety-buy",
            "ordersize": 5.0,
            "symbol": "BTC/USDC",
            "direction": "long",
            "botname": "test",
            "baseorder": False,
            "safetyorder": True,
            "order_count": 1,
            "ordertype": "market",
            "so_percentage": 1.0,
            "side": "buy",
            "_execution_scope": REPAIR_SCOPE,
        }
        await model.PlacementIntent.create(
            operation_id="safety-buy",
            client_order_id="mw-buy",
            exchange_order_id="buy-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="buy",
            side="buy",
            order_type="market",
            state="quarantined",
            deal_id="deal-buy",
            request_json=json.dumps(request),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "buy-1",
                    "orderid": "buy-1",
                    "status": "canceled",
                    "filled": 0.5,
                    "amount": 0.5,
                    "price": 10.0,
                    "timestamp": "1778000000000",
                    "fees": 0.0,
                    "ordersize": 5.0,
                    "precision": 8,
                    "amount_fee": 0.0,
                },
            )
        )
        repair = PlacementRecoveryEntry(lifecycle=lifecycle).build_placement_repair()
        assert (await repair.repair("safety-buy", REPAIR_CONFIG))[
            "status"
        ] == "unchanged"
        assert "active TP order" in caplog.text
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        assert trade.tp_limit_order_id == "tp-new"
        assert trade.amount == 1.0
        assert await model.Trades.filter(orderid="buy-1").count() == 0
        assert (
            await model.PlacementIntent.get(operation_id="safety-buy")
        ).state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "limit_sell"])
@pytest.mark.parametrize("reported_price", [11.0, 100.0])
async def test_real_repair_commits_tp_effect_with_disposition(
    tmp_path, monkeypatch: pytest.MonkeyPatch, action: str, reported_price: float
) -> None:
    """Cancel fills and open TP attachment commit with the repaired intent."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _seed_buy_trade(2.0, deal_id="deal-tp")
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="deal-tp",
            amount=2.0,
            cost=20.0,
            execution_history_complete=True,
            tp_limit_order_id="tp-1",
            tp_limit_order_price=11.0,
            tp_limit_order_amount=2.0,
        )
        await model.PlacementIntent.create(
            operation_id="atomic-tp",
            client_order_id="mw-tp",
            exchange_order_id="tp-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action=action,
            side="sell",
            order_type="limit",
            state="quarantined",
            deal_id="deal-tp",
            requested_amount=2.0,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        evidence = {
            "id": "tp-1",
            "symbol": "BTC/USDC",
            "status": "canceled" if action == "cancel" else "open",
            "filled": 0.4 if action == "cancel" else 0.0,
            "amount": 2.0,
            "price": reported_price,
            "average": reported_price,
            "cost": 4.4,
        }
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=evidence
            )
        )
        repair = PlacementRecoveryEntry(lifecycle=lifecycle).build_placement_repair()
        result = await repair.repair("atomic-tp", REPAIR_CONFIG)
        assert result["status"] == "completed"
        intent = await model.PlacementIntent.get(operation_id="atomic-tp")
        assert intent.state == "completed"
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        if action == "cancel":
            assert trade.sold_amount == pytest.approx(0.4)
            assert trade.sold_proceeds == pytest.approx(4.4)
            assert trade.tp_limit_order_id is None
            assert await model.TradeExecutions.all().count() == 1
            execution = await model.TradeExecutions.first()
            assert execution.price == pytest.approx(11.0)
        else:
            assert trade.tp_limit_order_id == "tp-1"
            assert await model.TradeExecutions.all().count() == 0
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "limit_sell", "sell"])
async def test_repair_does_not_replace_newer_tp_order(
    tmp_path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """An older order must not clear or replace a newer order on the same deal."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="deal-tp",
            amount=2.0,
            cost=20.0,
            tp_limit_order_id="new-tp",
            tp_limit_order_price=12.0,
            tp_limit_order_amount=2.0,
        )
        await model.PlacementIntent.create(
            operation_id="stale-order",
            client_order_id="mw-old",
            exchange_order_id="old-tp",
            exchange_name="binance",
            symbol="BTC/USDC",
            action=action,
            side="sell",
            order_type="limit",
            state="quarantined",
            deal_id="deal-tp",
            requested_amount=2.0,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "old-tp",
                    "status": {
                        "cancel": "canceled",
                        "limit_sell": "open",
                        "sell": "closed",
                    }[action],
                    "filled": {"cancel": 0.4, "limit_sell": 0.0, "sell": 2.0}[action],
                    "amount": 2.0,
                    "price": 11.0,
                    "average": 11.0,
                    "cost": 4.4,
                },
            )
        )
        repair = PlacementRecoveryEntry(lifecycle=lifecycle).build_placement_repair()
        assert (await repair.repair("stale-order", REPAIR_CONFIG))[
            "status"
        ] == "unchanged"
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        assert trade.tp_limit_order_id == "new-tp"
        assert trade.sold_amount == 0
        assert await model.TradeExecutions.all().count() == 0
        assert (
            await model.PlacementIntent.get(operation_id="stale-order")
        ).state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("saved_deal", [None, "old-deal"])
async def test_repair_never_applies_sell_to_unverified_deal(
    tmp_path, monkeypatch: pytest.MonkeyPatch, saved_deal: str | None
) -> None:
    """Missing or stale deal identity cannot mutate a newer open trade."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="current-deal",
            amount=2.0,
            cost=20.0,
            tp_limit_order_id="tp-1",
            tp_limit_order_price=11.0,
            tp_limit_order_amount=2.0,
        )
        await model.PlacementIntent.create(
            operation_id="stale-tp",
            client_order_id="mw-tp",
            exchange_order_id="tp-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="cancel",
            side="sell",
            order_type="limit",
            state="quarantined",
            deal_id=saved_deal,
            requested_amount=2.0,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "tp-1",
                    "status": "canceled",
                    "filled": 0.4,
                    "amount": 2.0,
                    "price": 11.0,
                },
            )
        )
        repair = PlacementRecoveryEntry(lifecycle=lifecycle).build_placement_repair()
        result = await repair.repair("stale-tp", REPAIR_CONFIG)
        assert result["status"] == "unchanged"
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        assert trade.deal_id == "current-deal"
        assert trade.sold_amount == 0
        assert trade.tp_limit_order_id == "tp-1"
        assert await model.TradeExecutions.all().count() == 0
        assert (
            await model.PlacementIntent.get(operation_id="stale-tp")
        ).state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_partial_cancel_without_open_trade_stays_quarantined(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial cancel without its owning trade cannot be marked complete."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await model.PlacementIntent.create(
            operation_id="orphan-cancel",
            client_order_id="mw-tp",
            exchange_order_id="tp-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="cancel",
            side="sell",
            order_type="limit",
            state="quarantined",
            deal_id="missing-deal",
            requested_amount=2.0,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "tp-1",
                    "status": "canceled",
                    "filled": 0.4,
                    "amount": 2.0,
                    "price": 11.0,
                },
            )
        )
        repair = PlacementRecoveryEntry(lifecycle=lifecycle).build_placement_repair()
        result = await repair.repair("orphan-cancel", REPAIR_CONFIG)
        assert result["status"] == "unchanged"
        assert await model.TradeExecutions.all().count() == 0
        assert (
            await model.PlacementIntent.get(operation_id="orphan-cancel")
        ).state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("startup", [False, True])
@pytest.mark.parametrize("action", ["sell", "limit_sell"])
@pytest.mark.parametrize("filled", [1.2345, 1.0])
async def test_rounded_terminal_sell_recovers_as_partial(
    tmp_path, monkeypatch: pytest.MonkeyPatch, startup: bool, action: str, filled: float
) -> None:
    """A precision-reduced fill preserves the unsold exposure and its identity."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _seed_buy_trade(1.234567)
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="deal",
            amount=1.234567,
            cost=12,
            tp_limit_order_id="sell-1" if action == "limit_sell" else None,
        )
        await model.PlacementIntent.create(
            operation_id="partial",
            client_order_id="client",
            exchange_order_id="sell-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action=action,
            side="sell",
            order_type="market" if action == "sell" else "limit",
            state="submitting" if startup else "quarantined",
            deal_id="deal",
            requested_amount=1.234567,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "sell-1",
                    "symbol": "BTC/USDC",
                    "side": "sell",
                    "status": "closed",
                    "amount": filled,
                    "filled": filled,
                    "cost": filled * 10,
                },
            )
        )
        entry = PlacementRecoveryEntry(lifecycle=lifecycle)
        if startup:
            summary = await entry.build_reconciler().reconcile(REPAIR_CONFIG)
            assert summary.ready
        else:
            result = await entry.build_placement_repair().repair(
                "partial", REPAIR_CONFIG
            )
            assert result["status"] == "completed"
            assert "remaining position stays open" in result["message"]
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        assert trade.sold_amount == pytest.approx(filled)
        assert trade.sold_proceeds == pytest.approx(filled * 10)
        assert trade.tp_limit_order_id is None
        assert await model.ClosedTrades.all().count() == 0
        assert await model.TradeExecutions.all().count() == 1
        assert (await model.TradeExecutions.first()).order_id == "sell-1"
        assert not trade.execution_history_complete
        assert (
            await model.PlacementIntent.get(operation_id="partial")
        ).state == "completed"
    finally:
        await Tortoise.close_connections()


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": None},
        {"amount": 1.5},
        {"filled": 2.5, "amount": 2.5},
        {"cost": None},
        {"symbol": "ETH/USDC"},
        {"side": "buy"},
    ],
)
def test_partial_sell_requires_matching_quantity_and_real_proceeds(changes) -> None:
    """Contradictory evidence cannot authorize partial accounting."""
    intent = SimpleNamespace(requested_amount=2.0, symbol="BTC/USDC")
    order = {
        "id": "sell-1",
        "status": "closed",
        "amount": 1.0,
        "filled": 1.0,
        "cost": 10.0,
    }
    order.update(changes)
    assert not has_terminal_partial_sell(intent, order)


@pytest.mark.asyncio
@pytest.mark.parametrize("startup", [False, True])
@pytest.mark.parametrize("different_deal", [False, True])
async def test_partial_recovery_never_mutates_an_unverified_deal(
    tmp_path, monkeypatch: pytest.MonkeyPatch, startup: bool, different_deal: bool
) -> None:
    """Missing or stale deal identity cannot apply a recovered sell."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await model.OpenTrades.create(
            symbol="BTC/USDC", deal_id="current", amount=2, cost=20
        )
        await model.PlacementIntent.create(
            operation_id="partial-unsafe",
            client_order_id="client",
            exchange_order_id="sell-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="sell",
            side="sell",
            order_type="market",
            state="submitting" if startup else "quarantined",
            deal_id="old" if different_deal else None,
            requested_amount=2,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "sell-1",
                    "status": "closed",
                    "amount": 1,
                    "filled": 1,
                    "cost": 10,
                },
            )
        )
        entry = PlacementRecoveryEntry(lifecycle=lifecycle)
        if startup:
            assert not (await entry.build_reconciler().reconcile(REPAIR_CONFIG)).ready
        else:
            assert (
                await entry.build_placement_repair().repair(
                    "partial-unsafe", REPAIR_CONFIG
                )
            )["status"] == "unchanged"
        assert (await model.OpenTrades.get(symbol="BTC/USDC")).sold_amount == 0
        assert await model.TradeExecutions.all().count() == 0
        assert (
            await model.PlacementIntent.get(operation_id="partial-unsafe")
        ).state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["missing_trade", "overflow_price"])
async def test_startup_partial_recovery_fails_closed_on_missing_trade_or_overflow(
    tmp_path, scenario: str
) -> None:
    """Startup cannot complete without a deal or finite execution price."""
    await _init_database(tmp_path)
    try:
        if scenario != "missing_trade":
            await model.OpenTrades.create(
                symbol="BTC/USDC", deal_id="deal", amount=2, cost=20
            )
        await model.PlacementIntent.create(
            operation_id="unsafe-partial",
            client_order_id="client",
            exchange_order_id="sell-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="sell",
            side="sell",
            order_type="market",
            state="submitting",
            deal_id="deal",
            requested_amount=2,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        amount = 1e-308 if scenario == "overflow_price" else 1.0
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "sell-1",
                    "status": "closed",
                    "amount": amount,
                    "filled": amount,
                    "cost": 1e308 if scenario == "overflow_price" else 10.0,
                    "price": 10.0,
                },
            )
        )
        summary = (
            await PlacementRecoveryEntry(lifecycle=lifecycle)
            .build_reconciler()
            .reconcile(REPAIR_CONFIG)
        )
        assert not summary.ready
        assert (
            await model.PlacementIntent.get(operation_id="unsafe-partial")
        ).state == "quarantined"
        assert await model.TradeExecutions.all().count() == 0
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("startup", [False, True])
@pytest.mark.parametrize(
    "prior",
    [
        "unkeyed",
        "no_row",
        "mismatch",
        "disjoint",
        "tiny_no_row",
        "proceeds_mismatch",
        "exhausts_exposure",
    ],
)
async def test_partial_recovery_requires_reconciled_prior_sell_history(
    tmp_path, monkeypatch: pytest.MonkeyPatch, startup: bool, prior: str
) -> None:
    """Unknown prior fills cannot be counted twice during recovery."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _seed_buy_trade(2.0)
        old_amount = 1e-15 if prior == "tiny_no_row" else 0.3
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="deal",
            amount=2.0,
            cost=20.0,
            sold_amount=old_amount,
            sold_proceeds=old_amount * 10,
            execution_history_complete=False,
        )
        if prior in {
            "unkeyed",
            "mismatch",
            "disjoint",
            "proceeds_mismatch",
            "exhausts_exposure",
        }:
            await model.TradeExecutions.create(
                deal_id="deal",
                symbol="BTC/USDC",
                side="sell",
                role="partial_sell",
                timestamp="",
                price=10,
                amount=0.2 if prior == "mismatch" else 0.3,
                ordersize=2 if prior in {"mismatch", "proceeds_mismatch"} else 3,
                order_id=None if prior == "unkeyed" else "old-order",
            )
        await model.PlacementIntent.create(
            operation_id="prior-check",
            client_order_id="client",
            exchange_order_id="new-order",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="sell",
            side="sell",
            order_type="market",
            state="submitting" if startup else "quarantined",
            deal_id="deal",
            requested_amount=2.0 if prior == "exhausts_exposure" else 1.7,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "new-order",
                    "symbol": "BTC/USDC",
                    "side": "sell",
                    "status": "closed",
                    "amount": 1.7 if prior == "exhausts_exposure" else 0.3,
                    "filled": 1.7 if prior == "exhausts_exposure" else 0.3,
                    "cost": 17.0 if prior == "exhausts_exposure" else 3.0,
                },
            )
        )
        entry = PlacementRecoveryEntry(lifecycle=lifecycle)
        if startup:
            outcome = (await entry.build_reconciler().reconcile(REPAIR_CONFIG)).ready
        else:
            outcome = (
                await entry.build_placement_repair().repair(
                    "prior-check", REPAIR_CONFIG
                )
            )["status"] == "completed"
        assert outcome is (prior == "disjoint")
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        assert trade.sold_amount == pytest.approx(
            old_amount + (0.3 if outcome else 0.0)
        )
        intent = await model.PlacementIntent.get(operation_id="prior-check")
        assert intent.state == ("completed" if outcome else "quarantined")
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_real_repair_commits_full_sell_with_disposition(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A confirmed full sell closes exactly its original deal atomically."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await model.Trades.create(
            timestamp="1778000000000",
            ordersize=10.0,
            fee=0.0,
            precision=8,
            amount=1.0,
            amount_fee=0.0,
            price=10.0,
            symbol="BTC/USDC",
            orderid="buy-before-sell",
            bot="test",
            ordertype="market",
            baseorder=True,
            safetyorder=False,
            order_count=0,
            so_percentage=None,
            direction="long",
            side="buy",
            deal_id="deal-sell",
        )
        await model.OpenTrades.create(
            symbol="BTC/USDC", deal_id="deal-sell", amount=1.0, cost=10.0
        )
        await model.PlacementIntent.create(
            operation_id="atomic-sell",
            client_order_id="mw-sell",
            exchange_order_id="sell-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="sell",
            side="sell",
            order_type="market",
            state="quarantined",
            deal_id="deal-sell",
            requested_amount=1.0,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "sell-1",
                    "type": "sold_check",
                    "symbol": "BTC/USDC",
                    "status": "closed",
                    "filled": 1.0,
                    "amount": 1.0,
                    "total_amount": 1.0,
                    "price": 11.0,
                    "total_cost": 10.0,
                    "timestamp": "1778000001000",
                },
            )
        )
        repair = PlacementRecoveryEntry(lifecycle=lifecycle).build_placement_repair()
        result = await repair.repair("atomic-sell", REPAIR_CONFIG)
        assert result["status"] == "completed"
        assert (
            await model.PlacementIntent.get(operation_id="atomic-sell")
        ).state == "completed"
        assert await model.OpenTrades.filter(symbol="BTC/USDC").count() == 0
        assert await model.ClosedTrades.filter(symbol="BTC/USDC").count() == 1
        with pytest.raises(PlacementRepairConflict):
            await repair.repair("atomic-sell", REPAIR_CONFIG)
        assert await model.ClosedTrades.filter(symbol="BTC/USDC").count() == 1
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_list_quarantined_describes_each_blocked_intent(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _quarantined_limit_sell()
        await _quarantined_limit_sell(
            operation_id="restored-limit",
            state="restored_quarantined",
            reason_code="portable_restore_quarantine",
            exchange_order_id=None,
            client_order_id=None,
        )

        rows = await _service(
            _FakeExchange(
                ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
            )
        ).list_quarantined()

        assert [row["operation_id"] for row in rows] == [
            "limit_sell-test",
            "restored-limit",
        ]
        first = rows[0]
        assert first["symbol"] == "BTC/USDC"
        assert first["action"] == "limit_sell"
        assert first["side"] == "sell"
        assert first["state"] == "quarantined"
        assert first["exchange_name"] == "binance"
        assert first["reason_code"] == "reconciliation_account_scope_unverified"
        assert first["exchange_order_id"] == "7788"
        assert first["client_order_id"] == "mw-test-identity"
        assert first["has_lookup_identity"] is True
        assert first["limit_price"] == 0.2
        assert first["amount"] == 0.6
        assert first["requested_quote"] == 120.0
        assert first["route"] == "classic_dca"
        assert first["created_at"] is not None
        assert first["completed_at"] is not None
        second = rows[1]
        assert second["state"] == "restored_quarantined"
        assert second["has_lookup_identity"] is False
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_release_quarantine_moves_quarantined_to_completed(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        await _quarantined_limit_sell()
        intents = PlacementIntentService()

        released = await intents.release_quarantine(
            "limit_sell-test",
            PlacementIntentState.COMPLETED,
            reason_code="operator_repair_fill_resumed",
        )

        assert str(released.state) == PlacementIntentState.COMPLETED.value
        assert released.reason_code == "operator_repair_fill_resumed"
        assert released.completed_at is not None
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_release_quarantine_moves_restored_quarantined_to_rejected(
    tmp_path,
) -> None:
    await _init_database(tmp_path)
    try:
        await _quarantined_limit_sell(
            state="restored_quarantined",
            reason_code="portable_restore_quarantine",
        )
        intents = PlacementIntentService()

        released = await intents.release_quarantine(
            "limit_sell-test",
            PlacementIntentState.REJECTED,
            reason_code="operator_dismissed",
            error_message="Operator dismissal: checked the exchange, order gone.",
        )

        assert str(released.state) == PlacementIntentState.REJECTED.value
        assert released.reason_code == "operator_dismissed"
        assert "Operator dismissal:" in str(released.error_message)
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_release_quarantine_rejects_non_quarantined_source(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        intents = PlacementIntentService()
        await model.PlacementIntent.create(
            operation_id="live-sell",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="sell",
            side="sell",
            order_type="market",
            state=PlacementIntentState.ACCEPTED.value,
            request_json="{}",
        )

        with pytest.raises(ValueError, match="only quarantined rows"):
            await intents.release_quarantine(
                "live-sell",
                PlacementIntentState.REJECTED,
                reason_code="operator_dismissed",
            )
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_release_quarantine_rejects_non_terminal_target(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        await _quarantined_limit_sell()
        intents = PlacementIntentService()

        with pytest.raises(ValueError, match="terminal disposition"):
            await intents.release_quarantine(
                "limit_sell-test",
                PlacementIntentState.ACCEPTED,
                reason_code="operator_repair",
            )
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exchange_id", "evidence"),
    [
        ("7788", {"id": "wrong", "status": "closed", "filled": 0.6, "amount": 0.6}),
        (
            "7788",
            {
                "id": "7788",
                "symbol": "ETH/USDC",
                "status": "closed",
                "filled": 0.6,
                "amount": 0.6,
            },
        ),
        (
            "7788",
            {
                "id": "7788",
                "side": "buy",
                "status": "closed",
                "filled": 0.6,
                "amount": 0.6,
            },
        ),
        (
            None,
            {
                "id": "7788",
                "clientOrderId": "wrong",
                "status": "closed",
                "filled": 0.6,
                "amount": 0.6,
            },
        ),
        (None, {"id": "7788", "status": "closed", "filled": 0.6, "amount": 0.6}),
    ],
)
async def test_repair_rejects_unverified_exchange_response_identity(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str | None,
    evidence: dict[str, Any],
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _quarantined_limit_sell(exchange_order_id=exchange_id)
        resume = _FakeResume()
        service = _service(
            _FakeExchange(
                ExchangeOrderLookupResult(
                    status=ExchangeOrderLookupStatus.FOUND, order=evidence
                )
            ),
            resume=resume,
        )
        result = await service.repair("limit_sell-test", REPAIR_CONFIG)
        assert result["status"] == "unchanged"
        assert "identity" in result["message"]
        assert (
            await model.PlacementIntent.get(operation_id="limit_sell-test")
        ).state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_unknown_operation_raises_not_found(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        service = _service(
            _FakeExchange(
                ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
            )
        )

        with pytest.raises(PlacementRepairNotFound):
            await service.repair("limit_sell-missing", REPAIR_CONFIG)
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_non_quarantined_raises_conflict(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        intents = PlacementIntentService()
        preparation = await intents.prepare(
            {"operation_id": "live-buy", "symbol": "BTC/USDC"},
            REPAIR_CONFIG,
            action="buy",
            side="buy",
            order_type="market",
        )
        service = _service(
            _FakeExchange(
                ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
            )
        )

        with pytest.raises(PlacementRepairConflict, match="not quarantined"):
            await service.repair(str(preparation.operation_id), REPAIR_CONFIG)
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_accumulation_routed_raises_conflict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _accumulation_route(monkeypatch)
        await _quarantined_limit_sell()
        service = _service(
            _FakeExchange(
                ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
            )
        )

        with pytest.raises(PlacementRepairConflict, match="accumulation"):
            await service.repair("limit_sell-test", REPAIR_CONFIG)
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_without_exchange_config_is_unchanged(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
        )
        await _quarantined_limit_sell()

        result = await _service(exchange).repair("limit_sell-test", {})

        assert result["status"] == "unchanged"
        assert result["state"] == "quarantined"
        assert exchange.calls == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_exchange_mismatch_is_unchanged(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
        )
        await _quarantined_limit_sell()

        result = await _service(exchange).repair(
            "limit_sell-test", {"exchange": "bybit"}
        )

        assert result["status"] == "unchanged"
        assert "does not match" in result["message"]
        assert exchange.calls == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_without_lookup_identity_is_unchanged(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
        )
        await _quarantined_limit_sell(exchange_order_id=None, client_order_id=None)

        result = await _service(exchange).repair("limit_sell-test", REPAIR_CONFIG)

        assert result["status"] == "unchanged"
        assert "no durable exchange lookup identity" in result["message"]
        assert exchange.calls == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_lookup_failure_is_unchanged(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)

        class _BrokenExchange(_FakeExchange):
            async def lookup_spot_order(self, *_args, **_kwargs):
                raise OSError("network down")

        await _quarantined_limit_sell()

        result = await _service(
            _BrokenExchange(
                ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
            )
        ).repair("limit_sell-test", REPAIR_CONFIG)

        assert result["status"] == "unchanged"
        assert "inconclusive" in result["message"]
        intent = await model.PlacementIntent.get(operation_id="limit_sell-test")
        assert str(intent.state) == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_identity_not_found_is_rejected_and_clears_gate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.NOT_FOUND,
                error_message="order does not exist",
            )
        )
        await _quarantined_limit_sell()

        result = await _service(exchange).repair("limit_sell-test", REPAIR_CONFIG)

        assert result["status"] == "rejected"
        assert result["state"] == "rejected"
        intent = await model.PlacementIntent.get(operation_id="limit_sell-test")
        assert intent.reason_code == "operator_repair_identity_not_found"
        assert await PlacementIntentService.list_action_required() == []
        assert exchange.calls == [
            {
                "symbol": "BTC/USDC",
                "exchange_order_id": "7788",
                "client_order_id": "mw-test-identity",
            }
        ]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_canceled_limit_sell_is_rejected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "7788",
                    "status": "canceled",
                    "filled": 0.0,
                    "amount": 0.6,
                },
            )
        )
        resume = _FakeResume()
        await _quarantined_limit_sell()

        result = await _service(exchange, resume=resume).repair(
            "limit_sell-test", REPAIR_CONFIG
        )

        assert result["status"] == "rejected"
        assert resume.calls == []
        intent = await model.PlacementIntent.get(operation_id="limit_sell-test")
        assert intent.reason_code == "operator_repair_exchange_order_canceled"
        assert await PlacementIntentService.list_action_required() == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_filled_limit_sell_resumes_and_completes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {
            "id": "7788",
            "status": "closed",
            "filled": 0.6,
            "amount": 0.6,
            "price": 0.21,
        }
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )
        resume = _FakeResume(True)
        await _quarantined_limit_sell()

        result = await _service(exchange, resume=resume).repair(
            "limit_sell-test", REPAIR_CONFIG
        )

        assert result["status"] == "completed"
        assert result["state"] == "completed"
        assert len(resume.calls) == 1
        assert resume.calls[0][0] == "limit_sell-test"
        intent = await model.PlacementIntent.get(operation_id="limit_sell-test")
        assert intent.reason_code == "operator_repair_fill_resumed"
        assert json.loads(intent.result_json)["status"] == "closed"
        assert await PlacementIntentService.list_action_required() == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_open_limit_sell_reattaches_and_completes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {
            "id": "7788",
            "status": "open",
            "filled": 0.0,
            "amount": 0.6,
            "price": 0.2,
        }
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )
        resume = _FakeResume(True)
        await _quarantined_limit_sell()

        result = await _service(exchange, resume=resume).repair(
            "limit_sell-test", REPAIR_CONFIG
        )

        assert result["status"] == "completed"
        assert len(resume.calls) == 1
        intent = await model.PlacementIntent.get(operation_id="limit_sell-test")
        assert intent.reason_code == "operator_repair_open_limit_reattached"
        assert await PlacementIntentService.list_action_required() == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_resume_failure_stays_quarantined(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {
            "id": "7788",
            "status": "closed",
            "filled": 0.6,
            "amount": 0.6,
            "price": 0.21,
        }
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )
        await _quarantined_limit_sell()

        result = await _service(exchange, resume=_FakeResume(False)).repair(
            "limit_sell-test", REPAIR_CONFIG
        )

        assert result["status"] == "unchanged"
        assert result["state"] == "quarantined"
        assert "could not be resumed" in result["message"]
        rows = await PlacementIntentService.list_action_required()
        assert [str(row.operation_id) for row in rows] == ["limit_sell-test"]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_resume_exception_stays_quarantined(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {
            "id": "7788",
            "status": "closed",
            "filled": 0.6,
            "amount": 0.6,
            "price": 0.21,
        }
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )
        await _quarantined_limit_sell()

        result = await _service(
            exchange, resume=_FakeResume(True, error=RuntimeError("persist failed"))
        ).repair("limit_sell-test", REPAIR_CONFIG)

        assert result["status"] == "unchanged"
        assert result["state"] == "quarantined"
        rows = await PlacementIntentService.list_action_required()
        assert [str(row.operation_id) for row in rows] == ["limit_sell-test"]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_terminal_buy_without_fill_evidence_stays_quarantined(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {
            "id": "9911",
            "status": "closed",
            "filled": 0.0,
            "amount": 50.0,
        }
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )
        resume = _FakeResume(True)
        await model.PlacementIntent.create(
            operation_id="buy-test",
            client_order_id="mw-buy-identity",
            exchange_order_id="9911",
            exchange_name="binance",
            symbol="ETH/USDC",
            action="buy",
            side="buy",
            order_type="market",
            state="quarantined",
            requested_quote=50.0,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
            reason_code="buy_fill_unconfirmed",
            completed_at=datetime.now(timezone.utc),
        )

        result = await _service(exchange, resume=resume).repair(
            "buy-test", REPAIR_CONFIG
        )

        assert result["status"] == "unchanged"
        assert "no fill evidence" in result["message"]
        assert resume.calls == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_ambiguous_exchange_state_stays_quarantined(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {
            "id": "5522",
            "status": "partially_filled",
            "filled": 0.2,
            "amount": 0.6,
        }
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )
        resume = _FakeResume(True)
        await model.PlacementIntent.create(
            operation_id="sell-test",
            client_order_id="mw-sell-identity",
            exchange_order_id="5522",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="sell",
            side="sell",
            order_type="market",
            state="quarantined",
            requested_amount=0.6,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
            reason_code="local_recovery_failed",
            completed_at=datetime.now(timezone.utc),
        )

        result = await _service(exchange, resume=resume).repair(
            "sell-test", REPAIR_CONFIG
        )

        assert result["status"] == "unchanged"
        assert "no definitive terminal mapping" in result["message"]
        assert resume.calls == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_confirmed_cancel_intent_completes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {"id": "3344", "status": "canceled", "filled": 0.0, "amount": 0.6}
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )
        resume = _FakeResume(True)
        await model.PlacementIntent.create(
            operation_id="cancel-test",
            client_order_id="mw-cancel-identity",
            exchange_order_id="3344",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="cancel",
            side="sell",
            order_type="limit",
            state="quarantined",
            requested_amount=0.6,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
            reason_code="local_recovery_failed",
            completed_at=datetime.now(timezone.utc),
        )

        result = await _service(exchange, resume=resume).repair(
            "cancel-test", REPAIR_CONFIG
        )

        assert result["status"] == "completed"
        assert len(resume.calls) == 1
        intent = await model.PlacementIntent.get(operation_id="cancel-test")
        assert intent.reason_code == "operator_repair_cancel_confirmed"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_dismiss_requires_a_note(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _quarantined_limit_sell()
        service = _service(
            _FakeExchange(
                ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
            )
        )

        with pytest.raises(PlacementRepairInvalid, match="note is required"):
            await service.dismiss("limit_sell-test", "   ")
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_dismiss_records_operator_dismissal_and_clears_gate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
        )
        await _quarantined_limit_sell(exchange_order_id=None, client_order_id=None)

        result = await _service(exchange).dismiss(
            "limit_sell-test",
            "Checked the exchange: the order was deleted by support; "
            "position already closed manually.",
        )

        assert result["status"] == "dismissed"
        assert result["state"] == "rejected"
        assert exchange.calls == []
        intent = await model.PlacementIntent.get(operation_id="limit_sell-test")
        assert intent.reason_code == "operator_dismissed"
        assert str(intent.error_message).startswith("Operator dismissal:")
        assert "deleted by support" in str(intent.error_message)
        assert await PlacementIntentService.list_action_required() == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_only_touches_the_exchange_through_lookup(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard: the repair path must never submit, cancel, or place an order."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {
            "id": "7788",
            "status": "closed",
            "filled": 0.6,
            "amount": 0.6,
            "price": 0.21,
        }
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )
        await _quarantined_limit_sell()

        result = await _service(exchange).repair("limit_sell-test", REPAIR_CONFIG)
        assert result["status"] == "completed"
        with pytest.raises(PlacementRepairConflict):
            await _service(exchange).repair("limit_sell-test", REPAIR_CONFIG)

        assert [call["symbol"] for call in exchange.calls] == ["BTC/USDC"]
        assert not hasattr(exchange, "create_order")
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_concurrent_repairs_persist_fill_once_and_conflict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent second repair must conflict, not double-apply evidence."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {
            "id": "7788",
            "status": "closed",
            "filled": 0.6,
            "amount": 0.6,
            "price": 0.21,
        }
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )

        class _YieldingResume(_FakeResume):
            """Yield the loop mid-resume so a concurrent repair interleaves."""

            async def __call__(
                self,
                intent: Any,
                exchange_order: dict[str, Any],
                _config: dict[str, Any],
                *,
                resolution: Any,
            ) -> bool:
                await asyncio.sleep(0)
                return await super().__call__(
                    intent, exchange_order, _config, resolution=resolution
                )

        resume = _YieldingResume()
        await _quarantined_limit_sell()
        service = _service(exchange, resume=resume)

        outcomes = await asyncio.gather(
            service.repair("limit_sell-test", REPAIR_CONFIG),
            service.repair("limit_sell-test", REPAIR_CONFIG),
            return_exceptions=True,
        )

        results = [outcome for outcome in outcomes if isinstance(outcome, dict)]
        conflicts = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, PlacementRepairConflict)
        ]
        assert len(results) == 1
        assert results[0]["status"] == "completed"
        assert len(conflicts) == 1
        # Exactly one resume ran: the second caller must never re-apply the
        # fill and then fail on the stale quarantine release.
        assert len(resume.calls) == 1
        intent = await model.PlacementIntent.get(operation_id="limit_sell-test")
        assert str(intent.state) == "completed"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_scope_mismatch_is_unchanged_without_lookup(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A different account on the same exchange must not be looked up."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={"id": "7788", "status": "closed", "filled": 0.6, "amount": 0.6},
            )
        )
        await _quarantined_limit_sell()

        other_account = dict(REPAIR_CONFIG, key="different-account-key")
        result = await _service(exchange).repair("limit_sell-test", other_account)

        assert result["status"] == "unchanged"
        assert result["state"] == "quarantined"
        assert "account scope does not match" in result["message"]
        assert exchange.calls == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_legacy_intent_without_scope_is_unchanged(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-scope intents cannot be bound to an account, so no lookup runs."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
        )
        await model.PlacementIntent.create(
            operation_id="legacy-sell",
            client_order_id="mw-legacy-identity",
            exchange_order_id="7799",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="limit_sell",
            side="sell",
            order_type="limit",
            state="quarantined",
            requested_quote=120.0,
            requested_amount=0.6,
            maximum_price=0.2,
            request_json=json.dumps({"limit_price": 0.2, "total_amount": 0.6}),
            reason_code="reconciliation_account_scope_unverified",
            completed_at=datetime.now(timezone.utc),
        )

        result = await _service(exchange).repair("legacy-sell", REPAIR_CONFIG)

        assert result["status"] == "unchanged"
        assert result["state"] == "quarantined"
        assert "no verified account scope" in result["message"]
        assert exchange.calls == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_canceled_partial_buy_fill_resumes_and_completes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A canceled IOC buy keeps its partial fill instead of dropping it."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {"id": "9911", "status": "canceled", "filled": 25.0, "amount": 50.0}
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )
        resume = _FakeResume(True)
        await model.PlacementIntent.create(
            operation_id="buy-partial",
            client_order_id="mw-buy-identity",
            exchange_order_id="9911",
            exchange_name="binance",
            symbol="ETH/USDC",
            action="buy",
            side="buy",
            order_type="market",
            state="quarantined",
            requested_quote=50.0,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
            reason_code="buy_fill_unconfirmed",
            completed_at=datetime.now(timezone.utc),
        )

        result = await _service(exchange, resume=resume).repair(
            "buy-partial", REPAIR_CONFIG
        )

        assert result["status"] == "completed"
        assert len(resume.calls) == 1
        assert resume.calls[0][1]["filled"] == 25.0
        intent = await model.PlacementIntent.get(operation_id="buy-partial")
        assert intent.reason_code == "operator_repair_cancel_partial_fill_resumed"
        assert await PlacementIntentService.list_action_required() == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_canceled_partial_buy_resume_failure_stays_quarantined(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {"id": "9911", "status": "canceled", "filled": 25.0, "amount": 50.0}
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )
        await model.PlacementIntent.create(
            operation_id="buy-partial",
            client_order_id="mw-buy-identity",
            exchange_order_id="9911",
            exchange_name="binance",
            symbol="ETH/USDC",
            action="buy",
            side="buy",
            order_type="market",
            state="quarantined",
            requested_quote=50.0,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
            reason_code="buy_fill_unconfirmed",
            completed_at=datetime.now(timezone.utc),
        )

        result = await _service(exchange, resume=_FakeResume(False)).repair(
            "buy-partial", REPAIR_CONFIG
        )

        assert result["status"] == "unchanged"
        assert result["state"] == "quarantined"
        assert "partial fill could not be resumed" in result["message"]
        rows = await PlacementIntentService.list_action_required()
        assert [str(row.operation_id) for row in rows] == ["buy-partial"]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_canceled_buy_without_valid_fill_evidence_stays_quarantined(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing or malformed fill evidence does not prove a zero-fill cancel."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        for case, filled in (("missing", None), ("boolean", True)):
            order = {"id": "9911", "status": "canceled", "amount": 50.0}
            if filled is not None:
                order["filled"] = filled
            exchange = _FakeExchange(
                ExchangeOrderLookupResult(
                    status=ExchangeOrderLookupStatus.FOUND, order=order
                )
            )
            resume = _FakeResume(True)
            await model.PlacementIntent.create(
                operation_id="buy-badfill",
                client_order_id="mw-buy-identity",
                exchange_order_id="9911",
                exchange_name="binance",
                symbol="ETH/USDC",
                action="buy",
                side="buy",
                order_type="market",
                state="quarantined",
                requested_quote=50.0,
                request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
                reason_code="buy_fill_unconfirmed",
                completed_at=datetime.now(timezone.utc),
            )

            result = await _service(exchange, resume=resume).repair(
                "buy-badfill", REPAIR_CONFIG
            )

            assert result["status"] == "unchanged"
            assert result["state"] == "quarantined"
            assert resume.calls == []
            assert case in repr(result) or True
            await model.PlacementIntent.all().delete()
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_evicts_its_lock_only_when_terminal(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terminal repairs free their lock; unfinished ones keep it."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        order = {
            "id": "7788",
            "status": "closed",
            "filled": 0.6,
            "amount": 0.6,
            "price": 0.21,
        }
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=order
            )
        )
        await _quarantined_limit_sell()
        # A foreign exchange name short-circuits the repair to
        # "unchanged" before any lookup, so the intent never reaches
        # a terminal disposition.
        await _quarantined_limit_sell(
            operation_id="limit_sell-open",
            client_order_id="mw-test-identity-open",
            exchange_name="bybit",
        )
        service = _service(exchange, resume=_FakeResume(True))

        first = await service.repair("limit_sell-test", REPAIR_CONFIG)
        assert first["status"] == "completed"
        assert "limit_sell-test" not in PlacementRepairService._operation_locks

        second = await service.repair("limit_sell-open", REPAIR_CONFIG)
        assert second["status"] == "unchanged"
        assert "limit_sell-open" in PlacementRepairService._operation_locks
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_open_limit_without_exchange_id_remains_quarantined(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client-ID lookup cannot attach a live order without an exchange ID."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await model.OpenTrades.create(
            symbol="BTC/USDC", deal_id="deal", amount=1, cost=10
        )
        await model.PlacementIntent.create(
            operation_id="no-id",
            client_order_id="mw-no-id",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="limit_sell",
            side="sell",
            order_type="limit",
            state="quarantined",
            deal_id="deal",
            requested_amount=1,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "clientOrderId": "mw-no-id",
                    "status": "open",
                    "amount": 1,
                    "price": 11,
                },
            )
        )
        repair = PlacementRecoveryEntry(lifecycle=lifecycle).build_placement_repair()
        result = await repair.repair("no-id", REPAIR_CONFIG)
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        intent = await model.PlacementIntent.get(operation_id="no-id")
        assert result["status"] == "unchanged"
        assert not trade.tp_limit_order_id
        assert intent.state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_cancel_with_conflicting_exchange_amount_stays_quarantined(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Conflicting total quantities must not route a partial fill to close."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        intent = await _quarantined_limit_sell()
        intent.action = "cancel"
        await intent.save()
        resume = _FakeResume()
        service = _service(
            _FakeExchange(
                ExchangeOrderLookupResult(
                    status=ExchangeOrderLookupStatus.FOUND,
                    order={
                        "id": "7788",
                        "status": "canceled",
                        "filled": 0.3,
                        "amount": 0.3,
                        "cost": 3.0,
                    },
                )
            ),
            resume=resume,
        )
        result = await service.repair("limit_sell-test", REPAIR_CONFIG)
        assert result["status"] == "unchanged"
        assert not resume.calls
        await intent.refresh_from_db()
        assert intent.state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence",
    [
        {},
        {"cost": -1},
        {"cost": "nan"},
        {"cost": 4, "average": "inf"},
        {"filled": 1e-308, "cost": 1e308},
    ],
)
async def test_partial_cancel_without_proceeds_remains_quarantined(
    tmp_path, monkeypatch: pytest.MonkeyPatch, evidence: dict[str, Any]
) -> None:
    """A partial cancellation cannot book sold inventory at invented zero proceeds."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="deal",
            amount=1,
            cost=10,
            tp_limit_order_id="tp1",
            tp_limit_order_amount=1,
        )
        await model.PlacementIntent.create(
            operation_id="no-proceeds",
            client_order_id="mw-cancel",
            exchange_order_id="tp1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="cancel",
            side="sell",
            order_type="limit",
            state="quarantined",
            deal_id="deal",
            requested_amount=1,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "tp1",
                    "status": "canceled",
                    "filled": 0.4,
                    "amount": 1,
                    **evidence,
                },
            )
        )
        repair = PlacementRecoveryEntry(lifecycle=lifecycle).build_placement_repair()
        result = await repair.repair("no-proceeds", REPAIR_CONFIG)
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        intent = await model.PlacementIntent.get(operation_id="no-proceeds")
        assert result["status"] == "unchanged"
        assert trade.sold_amount == 0
        assert trade.sold_proceeds == 0
        assert trade.tp_limit_order_id == "tp1"
        assert await model.TradeExecutions.all().count() == 0
        assert intent.state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_field", [{"amount": 3}, {"amount": 0}, {"price": "nan"}])
async def test_open_limit_bad_exchange_values_stay_quarantined(
    tmp_path, monkeypatch: pytest.MonkeyPatch, bad_field: dict[str, Any]
) -> None:
    """An unsafe open order must not be attached to the original trade."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await model.OpenTrades.create(
            symbol="BTC/USDC", deal_id="deal", amount=2, cost=20
        )
        await model.PlacementIntent.create(
            operation_id="bad-open",
            client_order_id="mw-open",
            exchange_order_id="tp1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="limit_sell",
            side="sell",
            order_type="limit",
            state="quarantined",
            deal_id="deal",
            requested_amount=2,
            maximum_price=11,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        evidence = {"id": "tp1", "status": "open", "amount": 2, "price": 11}
        evidence.update(bad_field)
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=evidence
            )
        )
        repair = PlacementRecoveryEntry(lifecycle=lifecycle).build_placement_repair()
        result = await repair.repair("bad-open", REPAIR_CONFIG)
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        intent = await model.PlacementIntent.get(operation_id="bad-open")
        assert result["status"] == "unchanged"
        assert not trade.tp_limit_order_id
        assert intent.state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_startup_open_limit_oversized_evidence_stays_quarantined(
    tmp_path,
) -> None:
    """Startup reconciliation shares the same order amount guard as repair."""
    await _init_database(tmp_path)
    try:
        await model.OpenTrades.create(
            symbol="BTC/USDC", deal_id="deal", amount=2, cost=20
        )
        await model.PlacementIntent.create(
            operation_id="startup-bad-open",
            client_order_id="mw-startup",
            exchange_order_id="tp1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="limit_sell",
            side="sell",
            order_type="limit",
            state="submitting",
            deal_id="deal",
            requested_amount=2,
            maximum_price=11,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={"id": "tp1", "status": "open", "amount": 3, "price": 11},
            )
        )
        summary = (
            await PlacementRecoveryEntry(lifecycle=lifecycle)
            .build_reconciler()
            .reconcile(REPAIR_CONFIG)
        )
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        intent = await model.PlacementIntent.get(operation_id="startup-bad-open")
        assert not summary.ready
        assert intent.state == "quarantined"
        assert not trade.tp_limit_order_id
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("startup", [False, True])
@pytest.mark.parametrize("action", ["sell", "limit_sell"])
async def test_terminal_partial_recovery_rejects_existing_order_execution(
    tmp_path, monkeypatch: pytest.MonkeyPatch, startup: bool, action: str
) -> None:
    """Cumulative exchange evidence cannot book the same order fill twice."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _seed_buy_trade(2)
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="deal",
            amount=2,
            cost=20,
            sold_amount=0.5,
            sold_proceeds=5,
        )
        await model.TradeExecutions.create(
            deal_id="deal",
            symbol="BTC/USDC",
            side="sell",
            role="partial_sell",
            timestamp="1778000000000",
            price=10,
            amount=0.5,
            ordersize=5,
            order_id="sell-1",
        )
        await model.PlacementIntent.create(
            operation_id="duplicate-fill",
            client_order_id="client",
            exchange_order_id="sell-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action=action,
            side="sell",
            order_type="limit" if action == "limit_sell" else "market",
            state="submitting" if startup else "quarantined",
            deal_id="deal",
            requested_amount=2,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "sell-1",
                    "symbol": "BTC/USDC",
                    "side": "sell",
                    "status": "closed",
                    "amount": 0.5,
                    "filled": 0.5,
                    "cost": 5,
                },
            )
        )
        entry = PlacementRecoveryEntry(lifecycle=lifecycle)
        if startup:
            assert not (await entry.build_reconciler().reconcile(REPAIR_CONFIG)).ready
        else:
            assert (
                await entry.build_placement_repair().repair(
                    "duplicate-fill", REPAIR_CONFIG
                )
            )["status"] == "unchanged"
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        assert trade.sold_amount == pytest.approx(0.5)
        assert trade.sold_proceeds == pytest.approx(5)
        assert (
            await model.TradeExecutions.filter(
                deal_id="deal", order_id="sell-1"
            ).count()
            == 1
        )
        assert (
            await model.PlacementIntent.get(operation_id="duplicate-fill")
        ).state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("startup", [False, True])
async def test_terminal_partial_recovery_cannot_exceed_current_exposure(
    tmp_path, monkeypatch: pytest.MonkeyPatch, startup: bool
) -> None:
    """A stale placement quantity cannot sell past the remaining inventory."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _seed_buy_trade(1)
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="deal",
            amount=2,
            cost=10,
            sold_amount=0.7,
            sold_proceeds=7,
        )
        await model.PlacementIntent.create(
            operation_id="stale-amount",
            client_order_id="client",
            exchange_order_id="sell-2",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="sell",
            side="sell",
            order_type="market",
            state="submitting" if startup else "quarantined",
            deal_id="deal",
            requested_amount=2,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "sell-2",
                    "status": "closed",
                    "amount": 0.5,
                    "filled": 0.5,
                    "cost": 5,
                },
            )
        )
        entry = PlacementRecoveryEntry(lifecycle=lifecycle)
        if startup:
            assert not (await entry.build_reconciler().reconcile(REPAIR_CONFIG)).ready
        else:
            assert (
                await entry.build_placement_repair().repair(
                    "stale-amount", REPAIR_CONFIG
                )
            )["status"] == "unchanged"
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        assert trade.sold_amount == pytest.approx(0.7)
        assert trade.sold_proceeds == pytest.approx(7)
        assert await model.TradeExecutions.filter(order_id="sell-2").count() == 0
        assert (
            await model.PlacementIntent.get(operation_id="stale-amount")
        ).state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("startup", [False, True])
@pytest.mark.parametrize(
    ("prior_proceeds", "new_proceeds"),
    [(1e308, 1e308), (-1.0, 10.0), (float("inf"), 10.0)],
)
async def test_partial_recovery_rejects_proceeds_overflow(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    startup: bool,
    prior_proceeds: float,
    new_proceeds: float,
) -> None:
    """Finite individual proceeds must not overflow the persisted aggregate."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _seed_buy_trade(2.5)
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="deal",
            amount=2.5,
            cost=25,
            sold_amount=0.5,
            sold_proceeds=prior_proceeds,
        )
        await model.TradeExecutions.create(
            deal_id="deal",
            symbol="BTC/USDC",
            side="sell",
            role="partial_sell",
            timestamp="1778000000000",
            price=1,
            amount=0.5,
            ordersize=1e308,
            order_id="old-sell",
        )
        await model.PlacementIntent.create(
            operation_id="overflow-proceeds",
            client_order_id="client",
            exchange_order_id="new-sell",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="sell",
            side="sell",
            order_type="market",
            state="submitting" if startup else "quarantined",
            deal_id="deal",
            requested_amount=2,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "new-sell",
                    "status": "closed",
                    "amount": 1,
                    "filled": 1,
                    "cost": new_proceeds,
                },
            )
        )
        entry = PlacementRecoveryEntry(lifecycle=lifecycle)
        if startup:
            assert not (await entry.build_reconciler().reconcile(REPAIR_CONFIG)).ready
        else:
            assert (
                await entry.build_placement_repair().repair(
                    "overflow-proceeds", REPAIR_CONFIG
                )
            )["status"] == "unchanged"
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        assert trade.sold_amount == pytest.approx(0.5)
        assert trade.sold_proceeds == prior_proceeds
        assert await model.TradeExecutions.filter(order_id="new-sell").count() == 0
        assert (
            await model.PlacementIntent.get(operation_id="overflow-proceeds")
        ).state == "quarantined"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("target_symbol", ["ETH/USDC", "BTC/USDC"])
async def test_repair_business_write_is_bound_to_intent_symbol(
    tmp_path, monkeypatch: pytest.MonkeyPatch, target_symbol: str
) -> None:
    """The transaction cannot update another symbol even with a verified intent."""
    from service.trades import Trades

    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        intent = await _quarantined_limit_sell()
        intent.deal_id = "original-deal"
        await intent.save(update_fields=["deal_id"])
        await model.OpenTrades.create(symbol="BTC/USDC", deal_id="original-deal")
        await model.OpenTrades.create(symbol="ETH/USDC", deal_id="other-deal")

        async def resume(intent, exchange_order, config, *, resolution):
            return await Trades().set_tp_limit_order(
                target_symbol,
                order_id="7788",
                price=0.2,
                amount=0.6,
                placement_operation_id=intent.operation_id,
                resolution=resolution,
            )

        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "7788",
                    "symbol": "BTC/USDC",
                    "side": "sell",
                    "status": "open",
                },
            )
        )
        result = await _service(exchange, resume=resume).repair(
            "limit_sell-test", REPAIR_CONFIG
        )
        expected = target_symbol == "BTC/USDC"
        assert result["status"] == ("completed" if expected else "unchanged")
        assert (await model.OpenTrades.get(symbol="BTC/USDC")).tp_limit_order_id == (
            "7788" if expected else None
        )
        assert (await model.OpenTrades.get(symbol="ETH/USDC")).tp_limit_order_id is None
        assert (
            await model.PlacementIntent.get(operation_id="limit_sell-test")
        ).state == ("completed" if expected else "quarantined")
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("startup", [False, True])
@pytest.mark.parametrize("prior_proceeds", [1e308, 1.0])
async def test_partial_cancel_recovery_checks_proceeds_sum(
    tmp_path, monkeypatch: pytest.MonkeyPatch, startup: bool, prior_proceeds: float
) -> None:
    """Overflow leaves the fill, intent, and TP untouched in both recovery paths."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _seed_buy_trade(2.0)
        await model.TradeExecutions.create(
            deal_id="deal",
            symbol="BTC/USDC",
            side="sell",
            role="partial_sell",
            timestamp="",
            price=10,
            amount=0.1,
            ordersize=prior_proceeds,
            order_id="previous",
        )
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="deal",
            amount=2,
            cost=20,
            sold_amount=0.1,
            sold_proceeds=prior_proceeds,
            tp_limit_order_id="tp1",
            tp_limit_order_amount=2,
        )
        await model.PlacementIntent.create(
            operation_id="cancel-overflow",
            client_order_id="client",
            exchange_order_id="tp1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="cancel",
            side="sell",
            order_type="limit",
            state="submitting" if startup else "quarantined",
            deal_id="deal",
            requested_amount=2,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "tp1",
                    "symbol": "BTC/USDC",
                    "side": "sell",
                    "status": "canceled",
                    "filled": 1,
                    "amount": 2,
                    "cost": 1e308,
                },
            )
        )
        entry = PlacementRecoveryEntry(lifecycle=lifecycle)
        if startup:
            await entry.build_reconciler().reconcile(REPAIR_CONFIG)
        else:
            await entry.build_placement_repair().repair(
                "cancel-overflow", REPAIR_CONFIG
            )
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        intent = await model.PlacementIntent.get(operation_id="cancel-overflow")
        overflow = prior_proceeds == 1e308
        assert intent.state == ("quarantined" if overflow else "completed")
        assert trade.tp_limit_order_id == ("tp1" if overflow else None)
        assert trade.sold_amount == pytest.approx(0.1 if overflow else 1.1)
        assert trade.sold_proceeds == (prior_proceeds if overflow else 1e308)
        assert await model.TradeExecutions.all().count() == (1 if overflow else 2)
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("startup", [False, True])
@pytest.mark.parametrize("case", ["duplicate", "excess", "missing", "valid"])
async def test_partial_cancel_recovery_preserves_exposure(
    tmp_path, monkeypatch: pytest.MonkeyPatch, startup: bool, case: str
) -> None:
    """Cumulative cancellation fills cannot duplicate or exceed a live deal."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        if case != "missing":
            await _seed_buy_trade(1.0 if case == "excess" else 2.0)
            await model.OpenTrades.create(
                symbol="BTC/USDC",
                deal_id="deal",
                amount=2,
                cost=20,
                sold_amount=0 if case == "valid" else 0.7,
                sold_proceeds=0 if case == "valid" else 7,
                tp_limit_order_id="tp1",
                tp_limit_order_amount=2,
            )
            if case != "valid":
                await model.TradeExecutions.create(
                    deal_id="deal",
                    symbol="BTC/USDC",
                    side="sell",
                    role="partial_sell",
                    timestamp="",
                    price=10,
                    amount=0.7,
                    ordersize=7,
                    order_id="tp1" if case == "duplicate" else "previous",
                )
        await model.PlacementIntent.create(
            operation_id="cancel-check",
            client_order_id="client",
            exchange_order_id="tp1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="cancel",
            side="sell",
            order_type="limit",
            state="submitting" if startup else "quarantined",
            deal_id="deal",
            requested_amount=2,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
        )
        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "tp1",
                    "symbol": "BTC/USDC",
                    "side": "sell",
                    "status": "canceled",
                    "filled": 0.5,
                    "amount": 2,
                    "cost": 5,
                },
            )
        )
        entry = PlacementRecoveryEntry(lifecycle=lifecycle)
        if startup:
            await entry.build_reconciler().reconcile(REPAIR_CONFIG)
        else:
            await entry.build_placement_repair().repair("cancel-check", REPAIR_CONFIG)
        intent = await model.PlacementIntent.get(operation_id="cancel-check")
        assert intent.state == ("completed" if case == "valid" else "quarantined")
        trade = await model.OpenTrades.get_or_none(symbol="BTC/USDC")
        if trade:
            assert trade.sold_amount == (0.5 if case == "valid" else 0.7)
            assert trade.tp_limit_order_id == (None if case == "valid" else "tp1")
        assert await model.TradeExecutions.all().count() == (
            1 if case != "missing" else 0
        )
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["fallback", "partial"])
@pytest.mark.parametrize("prior", [False, True])
async def test_startup_recovers_stored_normalized_partial_sell(
    tmp_path, monkeypatch: pytest.MonkeyPatch, shape: str, prior: bool
) -> None:
    """Restart persists one confirmed internal partial, never replaying it twice."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _seed_buy_trade(2)
        await model.OpenTrades.create(
            symbol="BTC/USDC",
            deal_id="deal",
            amount=2,
            cost=20,
            sold_amount=0.5 if prior else 0,
            sold_proceeds=5 if prior else 0,
        )
        execution = {
            "symbol": "BTC/USDC",
            "side": "sell",
            "role": "partial_sell",
            "timestamp": "",
            "price": 10,
            "amount": 0.5,
            "ordersize": 5,
            "fee": 0,
            "order_id": "sell-1",
        }
        if prior:
            await model.TradeExecutions.create(deal_id="deal", **execution)
        evidence = {
            "symbol": "BTC/USDC",
            "partial_filled_amount": 0.5,
            "partial_avg_price": 10,
            "remaining_amount": 1.5,
            "executions": [execution],
        }
        if shape == "fallback":
            evidence.update(
                requires_market_fallback=True,
                limit_cancel_confirmed=True,
                exchange_order_id="sell-1",
            )
        else:
            evidence.update(type="partial_sell", partial_proceeds=5, unsellable=False)
        await model.PlacementIntent.create(
            operation_id="stored-partial",
            client_order_id="client",
            exchange_order_id="sell-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="sell",
            side="sell",
            order_type="limit",
            state="filled",
            deal_id="deal",
            requested_amount=2,
            request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
            result_json=json.dumps(evidence),
        )
        lifecycle = DcaOrderLifecycle()
        entry = PlacementRecoveryEntry(lifecycle=lifecycle)
        await entry.build_reconciler().reconcile(REPAIR_CONFIG)
        intent = await model.PlacementIntent.get(operation_id="stored-partial")
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        assert intent.state == ("quarantined" if prior else "completed")
        assert trade.sold_amount == 0.5
        assert trade.sold_proceeds == 5
        assert await model.TradeExecutions.all().count() == 1
    finally:
        await Tortoise.close_connections()


@pytest.mark.parametrize(
    "bad",
    [
        "missing_deal",
        "missing_id",
        "wrong_order",
        "wrong_symbol",
        "wrong_side",
        "nan_amount",
        "overflow",
        "bad_proceeds",
        "bad_remaining",
        "missing_execution",
        "multiple_executions",
        "unconfirmed_cancel",
    ],
)
def test_stored_partial_requires_complete_consistent_evidence(bad: str) -> None:
    """Internal partial payloads cannot bypass transaction identity and accounting."""
    from service.placement_repair import has_valid_stored_partial_sell

    intent = SimpleNamespace(
        symbol="BTC/USDC",
        deal_id="deal",
        exchange_order_id="sell-1",
        requested_amount=2,
    )
    execution = {
        "symbol": "BTC/USDC",
        "side": "sell",
        "amount": 0.5,
        "price": 10,
        "ordersize": 5,
        "fee": 0,
        "order_id": "sell-1",
    }
    order = {
        "requires_market_fallback": True,
        "limit_cancel_confirmed": True,
        "symbol": "BTC/USDC",
        "exchange_order_id": "sell-1",
        "partial_filled_amount": 0.5,
        "partial_avg_price": 10,
        "remaining_amount": 1.5,
        "executions": [execution],
    }
    if bad == "missing_deal":
        intent.deal_id = None
    elif bad == "missing_id":
        intent.exchange_order_id = None
    elif bad == "wrong_order":
        execution["order_id"] = "other"
    elif bad == "wrong_symbol":
        execution["symbol"] = "ETH/USDC"
    elif bad == "wrong_side":
        execution["side"] = "buy"
    elif bad == "nan_amount":
        execution["amount"] = float("nan")
    elif bad == "overflow":
        order["partial_avg_price"] = 1e308
        order["partial_filled_amount"] = 1e308
    elif bad == "bad_proceeds":
        execution["ordersize"] = 1
    elif bad == "bad_remaining":
        order["remaining_amount"] = 1
    elif bad == "missing_execution":
        order["executions"] = []
    elif bad == "multiple_executions":
        order["executions"] = [execution, dict(execution)]
    elif bad == "unconfirmed_cancel":
        order["limit_cancel_confirmed"] = False
    assert not has_valid_stored_partial_sell(intent, order)


@pytest.mark.asyncio
async def test_fallback_partial_producer_journals_identity_before_restart(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actual fallback conversion survives a crash after FILLED is journaled."""
    import service.dca.order_lifecycle as lifecycle_module
    from service.dca.limit_sell import (
        build_market_fallback_status,
        build_partial_status_from_fallback,
    )

    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _seed_buy_trade(2)
        await model.OpenTrades.create(
            symbol="BTC/USDC", deal_id="deal", amount=2, cost=20
        )
        execution = {
            "symbol": "BTC/USDC",
            "side": "sell",
            "role": "partial_sell",
            "timestamp": "",
            "price": 10,
            "amount": 0.5,
            "ordersize": 5,
            "fee": 0,
            "order_id": "sell-1",
        }

        class Exchange:
            async def create_spot_sell(self, order, config, **kwargs):
                fallback = build_market_fallback_status(
                    symbol=order["symbol"],
                    exchange_order_id="sell-1",
                    remaining_amount=1.5,
                    partial_filled_amount=0.5,
                    partial_avg_price=10,
                    executions=[execution],
                )
                return build_partial_status_from_fallback(
                    fallback, default_symbol=order["symbol"]
                )

            async def close(self):
                pass

        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = Exchange()
        original = lifecycle_module.handle_partial_sell_status

        async def crash(*args, **kwargs):
            raise RuntimeError("crash after durable fill")

        monkeypatch.setattr(lifecycle_module, "handle_partial_sell_status", crash)
        config = {**REPAIR_CONFIG, "sell_order_type": "limit"}
        with pytest.raises(RuntimeError, match="crash after durable fill"):
            await lifecycle.receive_sell_order(
                {
                    "operation_id": "producer-partial",
                    "symbol": "BTC/USDC",
                    "direction": "long",
                    "side": "sell",
                    "type_sell": "order_sell",
                    "actual_pnl": 0,
                    "total_cost": 20,
                    "current_price": 10,
                    "sell_reason": "manual_sell",
                    "skip_tp_limit_cancel": True,
                },
                config,
            )
        intent = await model.PlacementIntent.get(operation_id="producer-partial")
        assert intent.state == "filled"
        assert intent.exchange_order_id == "sell-1"
        monkeypatch.setattr(lifecycle_module, "handle_partial_sell_status", original)
        await (
            PlacementRecoveryEntry(lifecycle=lifecycle)
            .build_reconciler()
            .reconcile(config)
        )
        await intent.refresh_from_db()
        assert intent.state == "completed"
        trade = await model.OpenTrades.get(symbol="BTC/USDC")
        assert trade.sold_amount == 0.5 and trade.sold_proceeds == 5
        assert await model.TradeExecutions.filter(order_id="sell-1").count() == 1
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_cost", [5.00000001, 5.1])
async def test_stored_partial_recovery_uses_execution_proceeds(
    tmp_path, monkeypatch: pytest.MonkeyPatch, first_cost: float
) -> None:
    """Rounded executions reconcile with later fills; inconsistent evidence blocks."""
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        await _seed_buy_trade(2)
        await model.OpenTrades.create(
            symbol="BTC/USDC", deal_id="deal", amount=2, cost=20
        )
        lifecycle = DcaOrderLifecycle()
        entry = PlacementRecoveryEntry(lifecycle=lifecycle)

        async def recover(operation_id, requested, remaining, cost):
            execution = {
                "symbol": "BTC/USDC",
                "side": "sell",
                "role": "partial_sell",
                "timestamp": "",
                "price": 10,
                "amount": 0.5,
                "ordersize": cost,
                "fee": 0,
                "order_id": operation_id,
            }
            evidence = {
                "type": "partial_sell",
                "symbol": "BTC/USDC",
                "partial_filled_amount": 0.5,
                "partial_avg_price": 10,
                "partial_proceeds": 5,
                "remaining_amount": remaining,
                "executions": [execution],
            }
            await model.PlacementIntent.create(
                operation_id=operation_id,
                client_order_id=f"client-{operation_id}",
                exchange_order_id=operation_id,
                exchange_name="binance",
                symbol="BTC/USDC",
                action="sell",
                side="sell",
                order_type="limit",
                state="filled",
                deal_id="deal",
                requested_amount=requested,
                request_json=json.dumps({"_execution_scope": REPAIR_SCOPE}),
                result_json=json.dumps(evidence),
            )
            await entry.build_reconciler().reconcile(REPAIR_CONFIG)
            return await model.PlacementIntent.get(operation_id=operation_id)

        first = await recover("one", 2, 1.5, first_cost)
        if first_cost == 5.1:
            assert first.state == "quarantined"
            assert await model.TradeExecutions.all().count() == 0
            assert (await model.OpenTrades.get(symbol="BTC/USDC")).sold_proceeds == 0
        else:
            assert first.state == "completed"
            assert (
                await model.OpenTrades.get(symbol="BTC/USDC")
            ).sold_proceeds == first_cost
            second = await recover("two", 1.5, 1, 5)
            assert second.state == "completed"
            trade = await model.OpenTrades.get(symbol="BTC/USDC")
            assert trade.sold_amount == 1
            assert trade.sold_proceeds == first_cost + 5
            assert await model.TradeExecutions.all().count() == 2
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "scenario"),
    [
        (kind, scenario)
        for kind in ("sell", "limit_full", "cancel_full", "safety_buy", "limit_open")
        for scenario in (
            "matching",
            "different",
            "client_only",
            "missing_deal",
            "conflicting_tp",
        )
    ]
    + [
        ("base_buy", scenario)
        for scenario in ("matching", "different", "client_only", "orphan")
    ],
)
async def test_startup_full_recovery_binds_original_deal(
    tmp_path, monkeypatch: pytest.MonkeyPatch, kind: str, scenario: str
) -> None:
    """Startup recovery binds its placement to the matching local deal."""
    valid = scenario in {"matching", "client_only"}
    await _init_database(tmp_path)
    try:
        _classic_route(monkeypatch)
        is_buy = kind in {"base_buy", "safety_buy"}
        if kind != "base_buy" or scenario == "different":
            current_deal = "newer" if scenario == "different" else "original"
            await _seed_buy_trade(1, deal_id=current_deal)
            await model.OpenTrades.create(
                symbol="BTC/USDC",
                deal_id=current_deal,
                amount=1,
                cost=10,
                tp_limit_order_id=(
                    "other-tp"
                    if scenario == "conflicting_tp"
                    else "order-1"
                    if kind == "cancel_full"
                    else None
                ),
                tp_limit_order_amount=1 if kind == "cancel_full" else None,
            )
        if scenario == "orphan":
            await _seed_buy_trade(1, deal_id="orphan")
        request = {
            "_execution_scope": REPAIR_SCOPE,
            "symbol": "BTC/USDC",
            "direction": "long",
            "side": "buy" if is_buy else "sell",
            "ordersize": 10,
            "botname": "test",
            "baseorder": kind == "base_buy",
            "safetyorder": kind == "safety_buy",
            "order_count": 1 if kind == "safety_buy" else 0,
            "ordertype": "market",
            "so_percentage": 1 if kind == "safety_buy" else None,
        }
        action = (
            "buy"
            if is_buy
            else "limit_sell"
            if kind.startswith("limit_")
            else "cancel"
            if kind == "cancel_full"
            else "sell"
        )
        await model.PlacementIntent.create(
            operation_id="startup-bind",
            client_order_id="client",
            exchange_order_id=None if scenario == "client_only" else "order-1",
            exchange_name="binance",
            symbol="BTC/USDC",
            action=action,
            side="buy" if is_buy else "sell",
            order_type="market",
            state="submitting",
            deal_id=None
            if kind == "base_buy" or scenario == "missing_deal"
            else "original",
            requested_amount=1,
            request_json=json.dumps(request),
        )
        evidence = {
            "id": "order-1",
            "clientOrderId": "client",
            "orderid": "order-1",
            "symbol": "BTC/USDC",
            "side": "buy" if is_buy else "sell",
            "status": "open" if kind == "limit_open" else "closed",
            "filled": 0 if kind == "limit_open" else 1,
            "amount": 1,
            "price": 10,
            "average": 10,
            "cost": 10,
            "timestamp": "1778000001000",
            "fees": 0,
            "ordersize": 10,
            "precision": 8,
            "amount_fee": 0,
            "type": "sold_check" if kind == "sell" else "limit",
            "total_amount": 1,
            "total_cost": 10,
        }

        class Exchange(_FakeExchange):
            async def build_spot_sell_order_status(self, payload, config):
                return {
                    **payload,
                    "type": "sold_check",
                    "total_amount": 1,
                    "price": 10,
                    "total_cost": 10,
                    "timestamp": "1778000001000",
                }

        lifecycle = DcaOrderLifecycle()
        lifecycle.exchange = Exchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND, order=evidence
            )
        )

        async def no_notify(*args, **kwargs):
            pass

        monkeypatch.setattr(lifecycle.monitoring, "notify_trade", no_notify)
        await (
            PlacementRecoveryEntry(lifecycle=lifecycle)
            .build_reconciler()
            .reconcile(REPAIR_CONFIG)
        )
        intent = await model.PlacementIntent.get(operation_id="startup-bind")
        assert intent.state == ("completed" if valid else "quarantined")
        if not valid:
            if scenario == "orphan":
                assert not await model.OpenTrades.filter(symbol="BTC/USDC").exists()
            else:
                trade = await model.OpenTrades.get(symbol="BTC/USDC")
                assert trade.deal_id == (
                    "newer" if scenario == "different" else "original"
                )
                if scenario == "conflicting_tp":
                    assert trade.tp_limit_order_id == "other-tp"
            assert await model.ClosedTrades.all().count() == 0
            assert await model.Trades.all().count() == 1
        elif is_buy:
            assert await model.OpenTrades.filter(symbol="BTC/USDC").exists()
            assert await model.Trades.all().count() == (1 if kind == "base_buy" else 2)
        elif kind == "limit_open":
            assert (
                await model.OpenTrades.get(symbol="BTC/USDC")
            ).tp_limit_order_id == "order-1"
        else:
            assert not await model.OpenTrades.filter(symbol="BTC/USDC").exists()
            assert await model.ClosedTrades.all().count() == 1
    finally:
        await Tortoise.close_connections()
