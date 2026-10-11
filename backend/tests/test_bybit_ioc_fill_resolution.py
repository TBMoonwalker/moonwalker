"""Regression coverage for asynchronous Bybit IOC acknowledgement handling."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import ccxt.async_support as ccxt
import model
import pytest
from service.exchange_buy_manager import ExchangeBuyManager
from service.exchange_capabilities import (
    ExchangeOrderLookupResult,
    ExchangeOrderLookupStatus,
    ExchangePostSubmissionFailure,
)
from service.placement_intents import (
    PlacementAction,
    PlacementIntentService,
    PlacementIntentState,
)
from service.placement_reconciliation import PlacementReconciler
from tortoise import Tortoise


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filled,status", [(56.1, "closed"), (20.0, "canceled"), (0.0, "canceled")]
)
async def test_acknowledged_ioc_looks_up_existing_order(filled, status):
    ack = {"id": "bybit-order", "filled": None, "status": None}
    resolved = {
        "id": "bybit-order",
        "symbol": "DOGE/USDC",
        "filled": filled,
        "status": status,
        "amount": 56.1,
    }
    exchange = SimpleNamespace(
        id="bybiteu",
        create_order=AsyncMock(return_value=ack),
        fetch_order=AsyncMock(return_value=resolved),
        price_to_precision=lambda _s, p: str(p),
    )
    manager = ExchangeBuyManager(
        SimpleNamespace(info=lambda *_a: None), lambda: exchange
    )
    order = {
        "symbol": "DOGE/USDC",
        "amount": 56.1,
        "price": 0.08915,
        "maximum_buy_price": 0.08915,
        "ordertype": "market",
        "side": "buy",
        "operation_id": "buy-ack",
    }
    result = await manager.execute_market_buy(order)
    assert exchange.create_order.await_count == 1
    exchange.fetch_order.assert_awaited_with("bybit-order", "DOGE/USDC")
    if filled:
        assert result["filled"] == filled
    else:
        assert result is None


@pytest.mark.asyncio
async def test_lookup_timeout_preserves_accepted_identity():
    exchange = SimpleNamespace(
        id="bybiteu",
        create_order=AsyncMock(return_value={"id": "bybit-order", "filled": None}),
        fetch_order=AsyncMock(side_effect=ccxt.RequestTimeout("lookup timeout")),
        price_to_precision=lambda _s, p: str(p),
    )
    manager = ExchangeBuyManager(
        SimpleNamespace(info=lambda *_a: None), lambda: exchange
    )
    with pytest.raises(ExchangePostSubmissionFailure) as failure:
        await manager.execute_market_buy(
            {
                "symbol": "DOGE/USDC",
                "amount": 56.1,
                "price": 0.08915,
                "maximum_buy_price": 0.08915,
                "ordertype": "market",
                "side": "buy",
                "operation_id": "buy-ack",
            }
        )
    assert failure.value.order["id"] == "bybit-order"
    assert exchange.fetch_order.await_count == 1
    assert exchange.create_order.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filled,expected",
    [
        (20.0, "completed"),
        (0.0, "rejected"),
        (None, "accepted"),
        (float("nan"), "accepted"),
        (-1.0, "accepted"),
        (True, "accepted"),
        ("timeout", "accepted"),
    ],
)
async def test_runtime_reconciles_canceled_ioc_without_resubmission(
    tmp_path, filled, expected
):
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'ioc.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        intents = PlacementIntentService()
        config = {"exchange": "bybiteu", "market": "spot", "dry_run": False}
        await intents.prepare(
            {
                "operation_id": "buy-existing",
                "symbol": "DOGE/USDC",
                "safetyorder": True,
                "order_count": 1,
            },
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="limit",
        )
        await intents.claim_submission("buy-existing")
        await intents.transition(
            "buy-existing",
            PlacementIntentState.ACCEPTED,
            exchange_order_id="bybit-order",
        )
        evidence = {
            "id": "bybit-order",
            "status": "canceled",
            "filled": filled,
            "amount": 56.1,
        }
        exchange = SimpleNamespace(
            lookup_spot_order=AsyncMock(
                return_value=ExchangeOrderLookupResult(
                    status=ExchangeOrderLookupStatus.FOUND, order=evidence
                )
            )
        )

        if filled == "timeout":
            exchange.lookup_spot_order.side_effect = ccxt.RequestTimeout(
                "metadata read timeout"
            )

        async def persist(intent, _evidence, _config):
            await intents.transition(
                intent.operation_id, PlacementIntentState.PERSISTED
            )
            return True

        resume = AsyncMock(side_effect=persist)
        reconciler = PlacementReconciler(exchange, resume, intents)
        outcome = await reconciler.reconcile_operation("buy-existing", config)
        assert outcome == expected
        assert (await intents.get("buy-existing")).state == expected
        assert await model.PlacementIntent.all().count() == 1
        assert resume.await_count == (1 if expected == "completed" else 0)
        if expected == "completed":
            assert resume.call_args.args[1]["filled"] == filled
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_ack_waits_for_terminal_partial_fill_without_another_buy():
    exchange = SimpleNamespace(
        id="bybiteu",
        create_order=AsyncMock(return_value={"id": "bybit-order", "filled": None}),
        fetch_order=AsyncMock(
            side_effect=[
                {"id": "bybit-order", "filled": 5, "status": "open"},
                {"id": "bybit-order", "filled": 20, "status": "canceled"},
            ]
        ),
        price_to_precision=lambda _s, p: str(p),
    )
    manager = ExchangeBuyManager(
        SimpleNamespace(info=lambda *_a: None), lambda: exchange
    )
    result = await manager.execute_market_buy(
        {
            "symbol": "DOGE/USDC",
            "amount": 56.1,
            "price": 0.08915,
            "maximum_buy_price": 0.08915,
            "ordertype": "market",
            "side": "buy",
        }
    )
    assert result["filled"] == 20
    assert exchange.fetch_order.await_count == 2
    assert exchange.create_order.await_count == 1


@pytest.mark.asyncio
async def test_runtime_duplicate_buy_recovers_once_without_closing_client(
    tmp_path, monkeypatch
):
    from service.orders import Orders

    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'runtime.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        orders = Orders()
        intents = orders.placement_intents
        config = {"exchange": "bybiteu", "market": "spot", "dry_run": False}
        await intents.prepare(
            {"operation_id": "buy-existing", "symbol": "DOGE/USDC"},
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="limit",
        )
        await intents.claim_submission("buy-existing")
        await intents.transition(
            "buy-existing",
            PlacementIntentState.ACCEPTED,
            exchange_order_id="bybit-order",
        )
        evidence = {
            "id": "bybit-order",
            "status": "canceled",
            "filled": 20,
            "amount": 56.1,
        }
        exchange = SimpleNamespace(
            lookup_spot_order=AsyncMock(
                return_value=ExchangeOrderLookupResult(
                    status=ExchangeOrderLookupStatus.FOUND, order=evidence
                )
            ),
            create_spot_market_buy=AsyncMock(),
            close=AsyncMock(),
        )

        async def persist(intent, _evidence, _config):
            await intents.transition(
                intent.operation_id, PlacementIntentState.PERSISTED
            )
            return True

        resume = AsyncMock(side_effect=persist)
        reconciler = PlacementReconciler(exchange, resume, intents)
        lease = SimpleNamespace(bind_operation=AsyncMock(), release=AsyncMock())
        check = SimpleNamespace(ok=True, order_quote=5, required_quote=5)
        monkeypatch.setattr(
            orders,
            "capital_budget",
            SimpleNamespace(acquire_order_lease=AsyncMock(return_value=(lease, check))),
        )
        monkeypatch.setattr(orders, "_build_placement_reconciler", lambda: reconciler)
        monkeypatch.setattr(
            orders.placement_workflow,
            "begin",
            AsyncMock(
                return_value=SimpleNamespace(
                    completed=False,
                    claimed=False,
                    operation_id="buy-existing",
                    state="accepted",
                )
            ),
        )
        for _ in range(2):
            filled, precheck = await orders._execute_budgeted_buy_order(
                {"symbol": "DOGE/USDC", "maximum_buy_price": 0.08915}, config
            )
            assert filled is True
            assert precheck is None
        assert resume.await_count == 1
        assert exchange.lookup_spot_order.await_count == 1
        exchange.create_spot_market_buy.assert_not_awaited()
        exchange.close.assert_not_awaited()
        # The initial accepted read reserves no fresh capital. Only the
        # already-completed replay enters the existing admission path.
        orders.capital_budget.acquire_order_lease.assert_awaited_once()
        lease.release.assert_awaited_once()
    finally:
        await Tortoise.close_connections()


# Value: protects=accepted IOC identity cannot be replaced by a missing or foreign order;
# fails_when=identity validation permits finalizing another order;
# why_new=existing fixtures always return matching identity; seam=none;
# no_claim=live provider response integrity (mocked exchange).
@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "foreign-id", "foreign-symbol"])
async def test_acknowledged_ioc_rejects_untrusted_identity(case):
    ack = {"id": "bybit-order", "filled": None}
    evidence = {
        "id": "bybit-order",
        "symbol": "DOGE/USDC",
        "status": "closed",
        "filled": 20,
    }
    if case == "missing":
        ack.pop("id")
    elif case == "foreign-id":
        evidence["id"] = "another-order"
    else:
        evidence["symbol"] = "BTC/USDC"
    exchange = SimpleNamespace(
        id="bybiteu",
        create_order=AsyncMock(return_value=ack),
        fetch_order=AsyncMock(return_value=evidence),
        price_to_precision=lambda _s, p: str(p),
    )
    manager = ExchangeBuyManager(
        SimpleNamespace(info=lambda *_a: None), lambda: exchange
    )
    with pytest.raises(ExchangePostSubmissionFailure) as error:
        await manager.execute_market_buy(
            {
                "symbol": "DOGE/USDC",
                "amount": 56.1,
                "price": 0.08915,
                "maximum_buy_price": 0.08915,
                "ordertype": "market",
                "side": "buy",
            }
        )
    assert isinstance(error.value.cause, ValueError)
    assert exchange.create_order.await_count == 1
    assert exchange.fetch_order.await_count == (0 if case == "missing" else 1)
    assert error.value.order.get("id") == ack.get("id")


# Value: protects=stalled acknowledged IOC lookup is canceled without losing order identity;
# fails_when=local deadline disappears or timeout becomes a second submission;
# why_new=RequestTimeout fixture does not exercise asyncio deadline cancellation; seam=none;
# no_claim=production network latency (local stalled coroutine).
@pytest.mark.asyncio
async def test_acknowledged_ioc_deadline_cancels_lookup(monkeypatch):
    import asyncio

    from service import exchange_buy_manager

    original_timeout = asyncio.timeout
    cancelled = asyncio.Event()

    async def stalled(*_args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    exchange = SimpleNamespace(
        id="bybiteu",
        create_order=AsyncMock(return_value={"id": "bybit-order", "filled": None}),
        fetch_order=AsyncMock(side_effect=stalled),
        price_to_precision=lambda _s, p: str(p),
    )
    monkeypatch.setattr(
        exchange_buy_manager.asyncio, "timeout", lambda _seconds: original_timeout(0.01)
    )
    manager = ExchangeBuyManager(
        SimpleNamespace(info=lambda *_a: None), lambda: exchange
    )
    async with original_timeout(1):
        with pytest.raises(ExchangePostSubmissionFailure) as error:
            await manager.execute_market_buy(
                {
                    "symbol": "DOGE/USDC",
                    "amount": 56.1,
                    "price": 0.08915,
                    "maximum_buy_price": 0.08915,
                    "ordertype": "market",
                    "side": "buy",
                }
            )
    assert isinstance(error.value.cause, TimeoutError)
    assert cancelled.is_set()
    assert error.value.order["id"] == "bybit-order"
    assert exchange.create_order.await_count == 1
    assert exchange.fetch_order.await_count == 1


# Value: protects=temporary invisibility is retried only as reads and unresolved IOC stays pending;
# fails_when=OrderNotFound aborts early or retries place another buy;
# why_new=existing delayed fixture starts with a visible open order; seam=none;
# no_claim=real exchange consistency timing (mocked lookup sequence).
@pytest.mark.asyncio
@pytest.mark.parametrize("resolves", [True, False])
async def test_acknowledged_ioc_eventual_visibility_is_read_only(resolves):
    evidence = {
        "id": "bybit-order",
        "symbol": "DOGE/USDC",
        "status": "closed",
        "filled": 20,
    }
    sequence = (
        [ccxt.OrderNotFound("not yet visible"), evidence]
        if resolves
        else [ccxt.OrderNotFound("not yet visible")] * 3
    )
    exchange = SimpleNamespace(
        id="bybiteu",
        create_order=AsyncMock(return_value={"id": "bybit-order", "filled": None}),
        fetch_order=AsyncMock(side_effect=sequence),
        price_to_precision=lambda _s, p: str(p),
    )
    manager = ExchangeBuyManager(
        SimpleNamespace(info=lambda *_a: None), lambda: exchange
    )
    order = {
        "symbol": "DOGE/USDC",
        "amount": 56.1,
        "price": 0.08915,
        "maximum_buy_price": 0.08915,
        "ordertype": "market",
        "side": "buy",
    }
    if resolves:
        assert (await manager.execute_market_buy(order))["filled"] == 20
    else:
        with pytest.raises(ExchangePostSubmissionFailure) as error:
            await manager.execute_market_buy(order)
        assert error.value.order["id"] == "bybit-order"
    assert exchange.fetch_order.await_count == (2 if resolves else 3)
    assert exchange.create_order.await_count == 1


# Value: protects=unresolved lookup or contradictory fill never releases an accepted buy;
# fails_when=NOT_FOUND or ambiguous terminal evidence becomes rejection or persistence;
# why_new=existing canceled IOC table omits typed lookup and status boundaries; seam=none;
# no_claim=provider acceptance or trade accounting (lookup and persistence mocked).
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["not-found", "unavailable", "no-order", "open-partial", "closed-zero"]
)
async def test_runtime_unresolved_buy_remains_accepted(tmp_path, case):
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'pending.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        intents = PlacementIntentService()
        config = {"exchange": "bybiteu", "market": "spot", "dry_run": False}
        await intents.prepare(
            {"operation_id": "buy-pending", "symbol": "DOGE/USDC"},
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="limit",
        )
        await intents.claim_submission("buy-pending")
        await intents.transition(
            "buy-pending",
            PlacementIntentState.ACCEPTED,
            exchange_order_id="bybit-order",
        )
        status = ExchangeOrderLookupStatus.FOUND
        evidence = {"id": "bybit-order", "status": "open", "filled": 20}
        if case == "not-found":
            status, evidence = ExchangeOrderLookupStatus.NOT_FOUND, None
        elif case == "unavailable":
            status, evidence = ExchangeOrderLookupStatus.UNAVAILABLE, None
        elif case == "no-order":
            evidence = None
        elif case == "closed-zero":
            evidence = {"id": "bybit-order", "status": "closed", "filled": 0}
        exchange = SimpleNamespace(
            lookup_spot_order=AsyncMock(
                return_value=ExchangeOrderLookupResult(status=status, order=evidence)
            )
        )
        resume = AsyncMock()
        outcome = await PlacementReconciler(
            exchange, resume, intents
        ).reconcile_operation("buy-pending", config)
        assert outcome == "accepted"
        saved = await intents.get("buy-pending")
        assert saved.state == "accepted"
        assert saved.exchange_order_id == "bybit-order"
        assert saved.reason_code == (
            "runtime_fill_pending" if evidence is not None else "runtime_lookup_pending"
        )
        resume.assert_not_awaited()
        assert await model.PlacementIntent.all().count() == 1
    finally:
        await Tortoise.close_connections()


# Value: protects=accepted IOC recovery persists its partial fill exactly once through real handlers;
# fails_when=recovery loses fill accounting or a later signal creates another trade;
# why_new=existing runtime fixture mocks recovery construction and trade persistence; seam=none;
# no_claim=live exchange fill or raw CCXT normalization (normalized lookup fixture).
@pytest.mark.asyncio
@pytest.mark.parametrize("initial_state", ["accepted", "filled"])
async def test_runtime_recovery_persists_real_partial_fill_once(
    tmp_path, monkeypatch, initial_state
):
    from service.orders import Orders

    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'accounting.sqlite'}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()
    try:
        orders = Orders()
        intents = orders.placement_intents
        config = {"exchange": "bybiteu", "market": "spot", "dry_run": False}
        request = {
            "operation_id": "buy-accounted",
            "symbol": "DOGE/USDC",
            "baseorder": True,
            "safetyorder": False,
            "order_count": 0,
            "direction": "long",
            "botname": "ioc_test",
            "side": "buy",
            "ordertype": "limit",
            "so_percentage": None,
            "ordersize": 5,
            "maximum_buy_price": 0.08915,
        }
        await intents.prepare(
            request,
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="limit",
            requested_quote=5,
            reserved_quote=5,
        )
        await intents.claim_submission("buy-accounted")
        await intents.transition(
            "buy-accounted",
            PlacementIntentState.ACCEPTED,
            exchange_order_id="bybit-order",
        )
        evidence = {
            "id": "bybit-order",
            "orderid": "bybit-order",
            "symbol": "DOGE/USDC",
            "status": "canceled",
            "filled": 20,
            "amount": 20,
            "price": 0.089,
            "timestamp": "1791730000000",
            "ordersize": 1.78,
            "fees": 0.001,
            "precision": 5,
            "amount_fee": 0.0,
        }
        if initial_state == "filled":
            await intents.transition(
                "buy-accounted", PlacementIntentState.FILLED, result=evidence
            )
        exchange = SimpleNamespace(
            lookup_spot_order=AsyncMock(
                return_value=ExchangeOrderLookupResult(
                    status=ExchangeOrderLookupStatus.FOUND, order=evidence
                )
            ),
            create_spot_market_buy=AsyncMock(),
            close=AsyncMock(),
        )
        monkeypatch.setattr(orders, "exchange", exchange)
        monkeypatch.setattr(orders.monitoring, "notify_trade", AsyncMock())
        lease = SimpleNamespace(bind_operation=AsyncMock(), release=AsyncMock())
        check = SimpleNamespace(ok=True, order_quote=5, required_quote=5)
        monkeypatch.setattr(
            orders,
            "capital_budget",
            SimpleNamespace(acquire_order_lease=AsyncMock(return_value=(lease, check))),
        )
        for _ in range(2):
            result, precheck = await orders._execute_budgeted_buy_order(
                dict(request), config
            )
            assert result is True
            assert precheck is None
        assert await model.Trades.filter(orderid="bybit-order").count() == 1
        saved = await model.Trades.get(orderid="bybit-order")
        assert saved.amount == pytest.approx(20)
        assert saved.price == pytest.approx(0.089)
        assert saved.ordersize == pytest.approx(1.78)
        assert (await intents.get("buy-accounted")).state == "completed"
        assert await model.OpenTrades.filter(symbol="DOGE/USDC").count() == 1
        assert exchange.lookup_spot_order.await_count == (
            1 if initial_state == "accepted" else 0
        )
        exchange.create_spot_market_buy.assert_not_awaited()
        exchange.close.assert_not_awaited()
        # The initial accepted read reserves no fresh capital. Only the
        # already-completed replay enters the existing admission path.
        orders.capital_budget.acquire_order_lease.assert_awaited_once()
        lease.release.assert_awaited_once()
    finally:
        await Tortoise.close_connections()


# Value: protects=an accepted buy can resolve at a fully committed capital budget;
# fails_when=fresh capital admission blocks read-only recovery;
# why_new=earlier runtime fixtures always approve fresh capital; seam=none;
# no_claim=live exchange (real intents, fixture lookup and denied fresh budget).
@pytest.mark.asyncio
async def test_accepted_buy_recovers_before_denied_fresh_budget(tmp_path, monkeypatch):
    from service.orders import Orders

    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'full-budget.sqlite'}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()
    try:
        orders = Orders()
        config = {
            "exchange": "bybiteu",
            "market": "spot",
            "dry_run": False,
            "max_fund": 5,
        }
        await orders.placement_intents.prepare(
            {"operation_id": "buy-full-budget", "symbol": "DOGE/USDC"},
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="limit",
            requested_quote=5,
            reserved_quote=5,
        )
        await orders.placement_intents.claim_submission("buy-full-budget")
        await orders.placement_intents.transition(
            "buy-full-budget",
            PlacementIntentState.ACCEPTED,
            exchange_order_id="bybit-order",
        )
        exchange = SimpleNamespace(
            lookup_spot_order=AsyncMock(
                return_value=ExchangeOrderLookupResult(
                    status=ExchangeOrderLookupStatus.FOUND,
                    order={"id": "bybit-order", "status": "canceled", "filled": 0},
                )
            ),
            create_spot_market_buy=AsyncMock(),
            close=AsyncMock(),
        )
        monkeypatch.setattr(orders, "exchange", exchange)
        denied = SimpleNamespace(
            ok=False, to_precheck_result=lambda: {"reason": "capital_budget_exceeded"}
        )
        budget = SimpleNamespace(
            acquire_order_lease=AsyncMock(return_value=(None, denied))
        )
        monkeypatch.setattr(orders, "capital_budget", budget)
        filled, precheck = await orders._execute_budgeted_buy_order(
            {"symbol": "DOGE/USDC", "ordersize": 5}, config
        )
        assert filled is False
        assert precheck["reason"] == "placement_rejected"
        budget.acquire_order_lease.assert_not_awaited()
        exchange.lookup_spot_order.assert_awaited_once()
        exchange.create_spot_market_buy.assert_not_awaited()
        assert (
            await orders.placement_intents.get("buy-full-budget")
        ).state == "rejected"
    finally:
        await Tortoise.close_connections()


# Value: protects=canceled runtime reads preserve recoverable accepted identity;
# fails_when=cancellation strands the operation in reconciling;
# why_new=read-timeout fixtures do not exercise task cancellation; seam=none;
# no_claim=live exchange (injected cancellation, real durable transitions).
@pytest.mark.asyncio
async def test_canceled_runtime_read_can_recover_on_next_attempt(tmp_path):
    import asyncio

    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'cancel-read.sqlite'}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()
    try:
        intents = PlacementIntentService()
        config = {"exchange": "bybiteu", "market": "spot", "dry_run": False}
        await intents.prepare(
            {"operation_id": "buy-canceled-read", "symbol": "DOGE/USDC"},
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="limit",
        )
        await intents.claim_submission("buy-canceled-read")
        await intents.transition(
            "buy-canceled-read",
            PlacementIntentState.ACCEPTED,
            exchange_order_id="bybit-order",
        )
        exchange = SimpleNamespace(
            lookup_spot_order=AsyncMock(
                side_effect=[
                    asyncio.CancelledError(),
                    ExchangeOrderLookupResult(
                        status=ExchangeOrderLookupStatus.FOUND,
                        order={"id": "bybit-order", "status": "canceled", "filled": 0},
                    ),
                ]
            )
        )
        resume = AsyncMock()
        reconciler = PlacementReconciler(exchange, resume, intents)
        with pytest.raises(asyncio.CancelledError):
            await reconciler.reconcile_operation("buy-canceled-read", config)
        assert (await intents.get("buy-canceled-read")).state == "accepted"
        assert (
            await reconciler.reconcile_operation("buy-canceled-read", config)
            == "rejected"
        )
        assert exchange.lookup_spot_order.await_count == 2
        resume.assert_not_awaited()
    finally:
        await Tortoise.close_connections()
