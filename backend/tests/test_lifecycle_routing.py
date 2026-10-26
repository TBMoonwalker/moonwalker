"""Persisted ownership gates for DCA evaluation and shared legacy order paths."""

import asyncio
from unittest.mock import AsyncMock

import model
import pytest
import pytest_asyncio
from service.dca import Dca
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.lifecycle_routing import LifecycleRoute, load_lifecycle_route
from service.orders import Orders
from tortoise import Tortoise
from tortoise.exceptions import OperationalError


@pytest_asyncio.fixture
async def routing_db(tmp_path):
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'routing.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


async def _accumulation(*, holding=True, state="enabled"):
    row = (
        await model.OpenTrades.create(symbol="BTC/USDC", lifecycle_mode="accumulation")
        if holding
        else None
    )
    return await model.AccumulationActivation.create(
        symbol="BTC/USDC", account_scope="test-account", state=state, holding=row
    )


@pytest.mark.asyncio
async def test_routes_absent_legacy_unknown_and_inconsistent_ownership(routing_db):
    assert (await load_lifecycle_route("btc_usdc")).route == LifecycleRoute.CLASSIC_DCA
    holding = await model.OpenTrades.create(symbol="BTC/USDC")
    assert (await load_lifecycle_route("BTC/USDC")).route == LifecycleRoute.CLASSIC_DCA
    holding.lifecycle_mode = "mystery"
    await holding.save()
    assert (await load_lifecycle_route("BTC/USDC")).reason == "unknown_lifecycle_mode"
    holding.lifecycle_mode = "accumulation"
    await holding.save()
    assert (
        await load_lifecycle_route("BTC/USDC")
    ).reason == "accumulation_activation_missing"
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC", account_scope="test"
    )
    assert (await load_lifecycle_route("BTC/USDC")).reason == "lifecycle_conflict"
    activation.holding = holding
    await activation.save()
    assert (await load_lifecycle_route("BTC/USDC")).route == LifecycleRoute.ACCUMULATION
    holding.lifecycle_mode = "classic_dca"
    await holding.save()
    assert (await load_lifecycle_route("BTC/USDC")).reason == "lifecycle_conflict"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["enabled", "paused", "stopped"])
@pytest.mark.parametrize("holding", [True, False])
async def test_accumulation_never_enters_dca_history_or_exit_evaluation(
    routing_db, state, holding
):
    await _accumulation(holding=holding, state=state)
    dca = Dca()
    dca.trades.get_trades_for_orders = AsyncMock(
        side_effect=AssertionError("history must not load")
    )
    dca.autopilot.resolve_trading_policy = AsyncMock(
        side_effect=AssertionError("no Autopilot")
    )
    await dca.process_ticker_data(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 90}}, {}
    )
    dca.trades.get_trades_for_orders.assert_not_called()
    dca.autopilot.resolve_trading_policy.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["classic_dca", None])
async def test_legacy_dca_route_still_reaches_evaluator(routing_db, mode):
    if mode:
        await model.OpenTrades.create(symbol="BTC/USDC", lifecycle_mode=mode)
    dca = Dca()
    dca.trades.get_trades_for_orders = AsyncMock(return_value={"symbol": "BTC/USDC"})
    dca.statistic.get_profit = AsyncMock(return_value={"funds_locked": 0})
    dca.autopilot.resolve_trading_policy = AsyncMock(return_value=None)
    exits = AsyncMock()
    dca._Dca__calculate_tp = exits
    await dca.process_ticker_data(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 90}}, {}
    )
    exits.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "take_profit",
        "stop_loss",
        "trailing_take_profit",
        "autopilot_timeout",
        "manual_sell",
        None,
    ],
)
async def test_payload_cannot_authorize_an_accumulation_sale(routing_db, reason):
    await _accumulation()
    orders = Orders()
    orders.exchange.create_spot_sell = AsyncMock(
        side_effect=AssertionError("no exchange submission")
    )
    orders._cancel_tp_limit_order_locked = AsyncMock(
        side_effect=AssertionError("no cancellation before admission")
    )
    orders.placement_workflow.begin = AsyncMock(
        side_effect=AssertionError("no placement intent")
    )
    assert not await orders.receive_sell_order(
        {
            "symbol": "BTC/USDC",
            "sell_reason": reason,
            "lifecycle_mode": "classic_dca",
            "manual": True,
            "skip_tp_limit_cancel": True,
        },
        {},
    )
    orders.placement_workflow.begin.assert_not_called()
    orders.exchange.create_spot_sell.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_mutations_cannot_bypass_accumulation_lifecycle(routing_db):
    activation = await _accumulation()
    orders = Orders()
    orders.trades.get_trades_for_orders = AsyncMock(
        side_effect=AssertionError("no history")
    )
    orders.placement_workflow.begin = AsyncMock(side_effect=AssertionError("no order"))
    assert not await orders.arm_tp_limit_order({"symbol": "BTC/USDC"}, {})
    assert not await orders.receive_buy_order({"symbol": "BTC/USDC"}, {})
    async with lifecycle_mutation_coordinator.mutation("BTC/USDC"):
        assert not await orders.receive_buy_order_prelocked({"symbol": "BTC/USDC"}, {})
    assert not await orders.receive_buy_signal("BTC/USDC", 10, {})
    assert not await orders.receive_sell_signal("BTC/USDC", {})
    assert not await orders.receive_stop_signal("BTC/USDC", {})
    for call in (
        orders.receive_sell_signal_result("BTC/USDC", {}, operation_id="operator-1"),
        orders.receive_buy_signal_result("BTC/USDC", 10, {}, operation_id="operator-2"),
        orders.receive_stop_signal_result("BTC/USDC", {}, operation_id="operator-3"),
    ):
        result = await call
        assert result.reason_code == "accumulation_lifecycle_required"
        assert not result.applied
    with pytest.raises(ValueError, match="accumulation"):
        await orders.receive_manual_buy_add("BTC/USDC", "2000000000000", "10", "1", {})
    assert await model.OpenTrades.filter(id=activation.holding_id).exists()
    orders.trades.get_trades_for_orders.assert_not_called()


@pytest.mark.asyncio
async def test_stopped_zero_inventory_activation_blocks_asap_reentry(routing_db):
    await _accumulation(holding=False, state="stopped")
    orders = Orders()
    orders.placement_workflow.begin = AsyncMock(
        side_effect=AssertionError("no base order")
    )
    assert not await orders.receive_buy_order(
        {"symbol": "BTC/USDC", "baseorder": True}, {}
    )
    orders.placement_workflow.begin.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_mode_and_database_failure_block_order_admission(
    routing_db, monkeypatch
):
    await model.OpenTrades.create(symbol="BTC/USDC", lifecycle_mode="unknown")
    orders = Orders()
    result = await orders.receive_sell_signal_result("BTC/USDC", {})
    assert result.reason_code == "unknown_lifecycle_mode"
    monkeypatch.setattr(
        "service.orders.load_lifecycle_route",
        AsyncMock(side_effect=OperationalError("read failure")),
    )
    assert not await orders.receive_buy_order({"symbol": "BTC/USDC"}, {})
    assert not await orders.receive_sell_order({"symbol": "BTC/USDC"}, {})
    result = await orders.receive_buy_signal_result("BTC/USDC", 10, {})
    assert result.reason_code == "trade_state_unavailable"


@pytest.mark.asyncio
async def test_unreadable_ownership_skips_ticker_without_falling_back_to_dca(
    monkeypatch,
):
    monkeypatch.setattr(
        "service.dca.engine.load_lifecycle_route",
        AsyncMock(side_effect=OperationalError("database unavailable")),
    )
    dca = Dca()
    dca.trades.get_trades_for_orders = AsyncMock(
        side_effect=AssertionError("no history")
    )
    await dca.process_ticker_data(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 90}}, {}
    )
    dca.trades.get_trades_for_orders.assert_not_called()


@pytest.mark.asyncio
async def test_queued_buy_rechecks_ownership_inside_symbol_lock(routing_db):
    holding = await model.OpenTrades.create(symbol="BTC/USDC")
    orders = Orders()
    orders.placement_workflow.begin = AsyncMock(
        side_effect=AssertionError("no placement")
    )
    start = asyncio.Event()

    async def queued_buy():
        await start.wait()
        return await orders.receive_buy_order({"symbol": "BTC/USDC"}, {})

    # Create the contender outside the owning task's lock ContextVar scope.
    contender = asyncio.create_task(queued_buy())
    async with lifecycle_mutation_coordinator.mutation("BTC/USDC"):
        start.set()
        await asyncio.sleep(0)
        assert not contender.done()
        holding.lifecycle_mode = "accumulation"
        await holding.save()
        await model.AccumulationActivation.create(
            symbol="BTC/USDC", account_scope="test", holding=holding
        )
    assert not await contender
    orders.placement_workflow.begin.assert_not_called()


@pytest.mark.asyncio
async def test_existing_tp_order_can_still_be_cancelled_for_accumulation(routing_db):
    activation = await _accumulation()
    await model.OpenTrades.filter(id=activation.holding_id).update(
        tp_limit_order_id="old-limit"
    )
    orders = Orders()
    # No buy ledger is needed to cancel an unfilled exchange order.
    orders.exchange.cancel_spot_order = AsyncMock(
        return_value={
            "id": "old-limit",
            "status": "canceled",
            "filled": 0,
        }
    )
    assert await orders.cancel_tp_limit_order("BTC/USDC", {"dry_run": True})
    orders.exchange.cancel_spot_order.assert_awaited_once()
    holding = await model.OpenTrades.get(id=activation.holding_id)
    assert holding.tp_limit_order_id is None
    assert await model.AccumulationActivation.filter(id=activation.id).exists()


@pytest.mark.asyncio
async def test_activation_linked_to_another_symbol_is_blocked(routing_db):
    other = await model.OpenTrades.create(
        symbol="ETH/USDC", lifecycle_mode="accumulation"
    )
    await model.AccumulationActivation.create(
        symbol="BTC/USDC", account_scope="test", holding=other
    )
    assert (await load_lifecycle_route("BTC/USDC")).reason == "lifecycle_conflict"
