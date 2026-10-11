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
        assert lease.release.await_count == 2
    finally:
        await Tortoise.close_connections()
