"""Typed operator mutation result mapping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import model
import pytest
import pytest_asyncio
from service.lifecycle_snapshot import LifecycleSnapshotIdentity
from service.order_mutation_result import (
    OrderMutationResult,
    OrderMutationStatus,
)
from service.orders import Orders
from service.placement_intents import PlacementIntentState
from service.trades import TradeStateUnavailableError
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError


@pytest_asyncio.fixture
async def stopped_trade_db(tmp_path, monkeypatch):
    """Exercise operator stops against real isolated trade persistence."""
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'stop.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    orders = Orders()
    # Replay exchange repair is unrelated to the accounting transaction.
    monkeypatch.setattr(
        "service.order_persistence._repair_replay_archive_after_commit", AsyncMock()
    )
    monkeypatch.setattr(orders.exchange, "create_spot_sell", AsyncMock())
    monkeypatch.setattr(orders.monitoring, "notify_trade", AsyncMock())
    await model.Trades.create(
        symbol="BTC/USDC",
        deal_id="stop-deal",
        timestamp="1773580000000",
        ordersize=200.0,
        amount=2.0,
        price=100.0,
        fee=0.0,
        precision=8,
        amount_fee=0.0,
        orderid="stop-buy",
        bot="csv_signal",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        direction="long",
        side="buy",
        cost_includes_fees=True,
    )
    await model.OpenTrades.create(
        symbol="BTC/USDC",
        deal_id="stop-deal",
        amount=2.0,
        cost=200.0,
        current_price=120.0,
        avg_price=100.0,
        open_date="1773580000000",
    )
    await model.TradeExecutions.create(
        symbol="BTC/USDC",
        deal_id="stop-deal",
        side="buy",
        role="base_order",
        timestamp="1773580000000",
        price=100.0,
        amount=2.0,
        ordersize=200.0,
    )
    try:
        yield orders
    finally:
        await orders.trades.invalidate_trade_caches()
        await orders.trades.get_trade_by_ordertype.cache_clear()
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("price", [80.0, 100.0, 120.0])
async def test_operator_stop_records_market_value_without_selling(
    stopped_trade_db, price
):
    orders = stopped_trade_db
    await model.OpenTrades.filter(symbol="BTC/USDC").update(current_price=price)

    result = await orders.receive_stop_signal_result("BTC/USDC", {})

    assert result.applied
    closed = await model.ClosedTrades.get(symbol="BTC/USDC")
    assert closed.close_reason == "manual_stop"
    assert closed.deal_id == "stop-deal"
    assert closed.amount == pytest.approx(2.0)
    assert closed.cost == pytest.approx(200.0)
    assert closed.tp_price is None
    assert closed.profit is None
    assert closed.profit_percent is None
    assert closed.valuation_quantity == pytest.approx(2)
    assert closed.valuation_price == pytest.approx(price)
    from service.realized_trades import has_unverified_manual_stop_profit

    assert not await has_unverified_manual_stop_profit()
    assert not await model.OpenTrades.exists()
    assert not await model.Trades.exists()
    assert await model.TradeExecutions.filter(side="buy").count() == 1
    assert not await model.TradeExecutions.filter(side="sell").exists()
    orders.exchange.create_spot_sell.assert_not_awaited()
    orders.monitoring.notify_trade.assert_not_awaited()
    assert not (await orders.receive_stop_signal_result("BTC/USDC", {})).applied
    assert await model.ClosedTrades.all().count() == 1


@pytest.mark.asyncio
async def test_operator_stop_includes_fill_during_tp_cancellation(
    stopped_trade_db, monkeypatch
):
    orders = stopped_trade_db

    async def cancel_with_partial_fill(_symbol, _config):
        from service.order_persistence import persist_tp_limit_cancellation

        return await persist_tp_limit_cancellation(
            "BTC/USDC",
            {"filled": 0.5, "average": 110.0, "cost": 55.0, "timestamp": 1773580001000},
        )

    monkeypatch.setattr(
        orders, "_cancel_tp_limit_order_locked", cancel_with_partial_fill
    )
    assert (await orders.receive_stop_signal_result("BTC/USDC", {})).applied
    closed = await model.ClosedTrades.get(symbol="BTC/USDC")
    assert closed.amount == pytest.approx(2.0)
    assert closed.cost == pytest.approx(200.0)
    assert closed.profit is None
    assert closed.profit_percent is None
    assert closed.valuation_quantity == pytest.approx(1.5)
    assert closed.valuation_price == pytest.approx(120)
    from service.realized_trades import has_unverified_manual_stop_profit

    assert await has_unverified_manual_stop_profit()
    assert closed.tp_price == pytest.approx(110)
    assert await model.TradeExecutions.filter(role="partial_sell").count() == 1
    assert not await model.TradeExecutions.filter(role="final_sell").exists()


@pytest.mark.asyncio
async def test_legacy_manual_stop_profit_is_not_exposed_as_realized(stopped_trade_db):
    from service.realized_trades import (
        has_unverified_manual_stop_profit,
        realized_closed_trades,
    )

    await model.ClosedTrades.create(
        symbol="BTC/USDC", close_reason="manual_stop", profit=40, profit_percent=20
    )
    await model.ClosedTrades.create(symbol="ETH/USDC", profit=5)
    assert await has_unverified_manual_stop_profit()
    assert await realized_closed_trades().values_list("profit", flat=True) == [5]
    rows = await stopped_trade_db.trades.get_closed_trades()
    legacy = next(row for row in rows if row["symbol"] == "BTC/USDC")
    assert legacy["profit"] is None and legacy["profit_percent"] is None

    from controller.statistics import profit_statistics
    from httpx import ASGITransport, AsyncClient
    from litestar import Litestar

    app = Litestar(route_handlers=[profit_statistics], openapi_config=None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.get("/statistic/profit/0/daily")
    assert response.status_code == 409
    assert "incomplete" in response.text


@pytest.mark.asyncio
async def test_legacy_stop_permanently_marks_existing_profit_snapshots_unverified(
    stopped_trade_db,
    monkeypatch,
):
    from datetime import datetime, timedelta, timezone

    from controller.statistics import profit_overall_timeline
    from httpx import ASGITransport, AsyncClient
    from litestar import Litestar
    from service.database import Database

    legacy = await model.ClosedTrades.create(
        symbol="BTC/USDC", close_reason="manual_stop", profit=40
    )
    snapshot = await model.UpnlHistory.create(
        timestamp=datetime.now(timezone.utc), profit_overall=40
    )
    database = Database()
    database.db_url = "sqlite://fixture"
    await database._ensure_manual_stop_valuation()
    await legacy.delete()
    await snapshot.refresh_from_db()
    assert snapshot.profit_overall == 40
    assert not snapshot.performance_verified

    app = Litestar(route_handlers=[profit_overall_timeline], openapi_config=None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.get("/statistic/profit-overall/timeline")
    assert response.status_code == 409
    await model.UpnlHistory.filter(id=snapshot.id).update(
        timestamp=datetime.now(timezone.utc) - timedelta(days=366)
    )
    monkeypatch.setattr(
        "controller.statistics.statistic",
        SimpleNamespace(get_profit_overall_timeline=AsyncMock(return_value=[])),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.get("/statistic/profit-overall/timeline")
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("price", [0.0, -1.0, float("inf")])
async def test_operator_stop_rejects_invalid_valuation(stopped_trade_db, price):
    await model.OpenTrades.filter(symbol="BTC/USDC").update(current_price=price)
    assert not (
        await stopped_trade_db.receive_stop_signal_result("BTC/USDC", {})
    ).applied
    assert await model.OpenTrades.exists()
    assert await model.Trades.exists()
    assert await model.TradeExecutions.all().count() == 1
    assert not await model.ClosedTrades.exists()


@pytest.mark.asyncio
async def test_operator_stop_rolls_back_failed_closure(stopped_trade_db, monkeypatch):
    monkeypatch.setattr(
        model.ClosedTrades,
        "create",
        AsyncMock(side_effect=IntegrityError("write failed")),
    )
    assert not (
        await stopped_trade_db.receive_stop_signal_result("BTC/USDC", {})
    ).applied
    assert await model.OpenTrades.exists()
    assert await model.Trades.exists()
    assert await model.TradeExecutions.all().count() == 1
    assert not await model.ClosedTrades.exists()


@pytest.mark.asyncio
async def test_operator_stop_retains_trade_when_cancellation_fails(
    stopped_trade_db, monkeypatch
):
    monkeypatch.setattr(
        stopped_trade_db, "_cancel_tp_limit_order_locked", AsyncMock(return_value=False)
    )
    assert not (
        await stopped_trade_db.receive_stop_signal_result("BTC/USDC", {})
    ).applied
    assert await model.OpenTrades.exists()
    assert await model.Trades.exists()
    assert await model.TradeExecutions.all().count() == 1
    assert not await model.ClosedTrades.exists()


@pytest.mark.asyncio
async def test_operator_stop_values_unsellable_remainder(stopped_trade_db):
    await model.OpenTrades.filter(symbol="BTC/USDC").update(
        amount=0.01,
        cost=1.0,
        unsellable_amount=0.01,
        unsellable_reason="minimum_notional",
    )
    assert (await stopped_trade_db.receive_stop_signal_result("BTC/USDC", {})).applied
    closed = await model.ClosedTrades.get(symbol="BTC/USDC")
    assert closed.amount == pytest.approx(0.01)
    assert closed.cost == pytest.approx(1.0)
    assert closed.profit is None
    assert closed.valuation_quantity == pytest.approx(0.01)
    assert closed.valuation_price == pytest.approx(120)


@pytest.mark.asyncio
async def test_operator_stop_fails_closed_on_partial_read_error(
    stopped_trade_db, monkeypatch
):
    orders = stopped_trade_db
    fail_on_error_seen: list[bool] = []

    async def raise_unavailable(
        _symbol: str, *, fail_on_error: bool = False
    ) -> tuple[float, float]:
        fail_on_error_seen.append(fail_on_error)
        raise TradeStateUnavailableError("partial sell read unavailable")

    monkeypatch.setattr(orders.trades, "get_partial_sell_execution", raise_unavailable)

    assert not (await orders.receive_stop_signal_result("BTC/USDC", {})).applied
    assert fail_on_error_seen
    assert fail_on_error_seen[0] is True
    assert await model.OpenTrades.exists()
    assert await model.Trades.exists()
    assert await model.TradeExecutions.filter(side="buy").count() == 1
    assert not await model.ClosedTrades.exists()


def _trade(**overrides: Any) -> dict[str, Any]:
    trade = {
        "symbol": "BTC/USDC",
        "deal_id": "deal-1",
        "execution_count": 1,
        "safetyorders_count": 0,
        "safetyorders": [],
        "direction": "long",
        "bot": "manual_BTC/USDC",
        "current_price": 100.0,
        "total_cost": 100.0,
        "total_amount": 1.0,
        "fee": 0.0,
    }
    trade.update(overrides)
    return trade


class _TradeReader:
    def __init__(self, trade: dict[str, Any]) -> None:
        self.trade = trade

    async def get_trades_for_orders_fresh(
        self,
        _symbol: str,
    ) -> dict[str, Any]:
        return self.trade


class _MissingTradeReader:
    def __init__(self) -> None:
        self.delete_calls = 0

    async def get_trades_for_orders_fresh(
        self,
        _symbol: str,
    ) -> None:
        return None

    async def delete_open_trades(self, _symbol: str) -> None:
        self.delete_calls += 1


class _UnavailableTradeReader:
    async def get_trades_for_orders_authoritative(
        self,
        _symbol: str,
    ) -> None:
        raise TradeStateUnavailableError("database unavailable")


class _UnexpectedTradeReader:
    async def get_trades_for_orders_authoritative(
        self,
        _symbol: str,
    ) -> None:
        raise AssertionError("completed operation retries must not reload trade state")


class _SequenceTradeReader:
    def __init__(self, trades: list[dict[str, Any]]) -> None:
        self.trades = trades

    async def get_trades_for_orders_fresh(
        self,
        _symbol: str,
    ) -> dict[str, Any]:
        return self.trades.pop(0)


class _IntentReader:
    def __init__(self, intent: Any | None) -> None:
        self.intent = intent

    async def get(self, _operation_id: str) -> Any | None:
        return self.intent


def _intent(state: PlacementIntentState, reason: str | None = None) -> Any:
    return SimpleNamespace(
        state=state.value,
        reason_code=reason,
        exchange_order_id="exchange-1",
        client_order_id="client-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "preexisting", "expected_status"),
    [
        (
            PlacementIntentState.COMPLETED,
            True,
            OrderMutationStatus.DEDUPLICATED,
        ),
        (
            PlacementIntentState.INDETERMINATE,
            False,
            OrderMutationStatus.INDETERMINATE,
        ),
        (
            PlacementIntentState.ACCEPTED,
            False,
            OrderMutationStatus.INDETERMINATE,
        ),
        (
            PlacementIntentState.QUARANTINED,
            False,
            OrderMutationStatus.QUARANTINED,
        ),
        (
            PlacementIntentState.RESTORED_QUARANTINED,
            False,
            OrderMutationStatus.QUARANTINED,
        ),
        (
            PlacementIntentState.REJECTED,
            False,
            OrderMutationStatus.REJECTED,
        ),
    ],
)
async def test_placement_state_maps_to_typed_operator_outcome(
    state: PlacementIntentState,
    preexisting: bool,
    expected_status: OrderMutationStatus,
) -> None:
    config = {"dry_run": True}
    trade = _trade()
    snapshot = LifecycleSnapshotIdentity.from_trade(trade, config)
    orders = Orders()
    orders.trades = _TradeReader(trade)  # type: ignore[assignment]
    orders.placement_intents = _IntentReader(_intent(state))  # type: ignore[assignment]

    result = await orders._operator_mutation_result(
        order={"symbol": "BTC/USDC", "operation_id": "operation-1"},
        action="manual_sell",
        applied=state is PlacementIntentState.COMPLETED,
        preexisting_operation=preexisting,
        expected_snapshot=snapshot,
        config=config,
    )

    assert result.status is expected_status
    assert result.applied is (
        expected_status
        in {OrderMutationStatus.APPLIED, OrderMutationStatus.DEDUPLICATED}
    )
    assert result.to_dict()["status"] == expected_status.value


@pytest.mark.asyncio
async def test_missing_intent_distinguishes_applied_and_stale() -> None:
    config = {"dry_run": True}
    evaluated_trade = _trade()
    snapshot = LifecycleSnapshotIdentity.from_trade(evaluated_trade, config)
    orders = Orders()
    orders.placement_intents = _IntentReader(None)  # type: ignore[assignment]
    orders.trades = _TradeReader(evaluated_trade)  # type: ignore[assignment]

    applied = await orders._operator_mutation_result(
        order={"symbol": "BTC/USDC", "operation_id": "operation-1"},
        action="manual_buy",
        applied=True,
        preexisting_operation=False,
        expected_snapshot=snapshot,
        config=config,
    )
    orders.trades = _TradeReader(_trade(execution_count=2))  # type: ignore[assignment]
    stale = await orders._operator_mutation_result(
        order={"symbol": "BTC/USDC", "operation_id": "operation-2"},
        action="manual_buy",
        applied=False,
        preexisting_operation=False,
        expected_snapshot=snapshot,
        config=config,
    )

    assert applied.status is OrderMutationStatus.APPLIED
    assert stale.status is OrderMutationStatus.STALE
    assert stale.reason_code == "stale_snapshot"


@pytest.mark.asyncio
async def test_post_dispatch_recheck_fails_closed_when_trade_state_is_unavailable() -> (
    None
):
    config = {"dry_run": True}
    trade = _trade()
    snapshot = LifecycleSnapshotIdentity.from_trade(trade, config)
    orders = Orders()
    orders.placement_intents = _IntentReader(None)  # type: ignore[assignment]
    orders.trades = _UnavailableTradeReader()  # type: ignore[assignment]

    result = await orders._operator_mutation_result(
        order={"symbol": "BTC/USDC", "operation_id": "operation-1"},
        action="manual_buy",
        applied=False,
        preexisting_operation=False,
        expected_snapshot=snapshot,
        config=config,
    )

    assert result.status is OrderMutationStatus.REJECTED
    assert result.reason_code == "trade_state_unavailable"


def test_mutation_result_applied_property_rejects_unresolved_states() -> None:
    result = OrderMutationResult(
        operation_id="operation-1",
        symbol="BTC/USDC",
        action="manual_sell",
        status=OrderMutationStatus.INDETERMINATE,
        reason_code="exchange_response_lost",
        user_message="Unknown.",
    )

    assert result.applied is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "expected_action"),
    [
        ("receive_sell_signal_result", "manual_sell"),
        ("receive_buy_signal_result", "manual_buy"),
    ],
)
@pytest.mark.usefixtures("classic_lifecycle_route")
async def test_typed_order_result_reports_missing_trade(
    method_name: str,
    expected_action: str,
) -> None:
    orders = Orders()
    trade_reader = _MissingTradeReader()
    orders.trades = trade_reader  # type: ignore[assignment]
    method = getattr(orders, method_name)

    result = (
        await method("btc-usdc", 25.0, {"dry_run": True})
        if expected_action == "manual_buy"
        else await method("btc-usdc", {"dry_run": True})
    )

    assert result.status is OrderMutationStatus.REJECTED
    assert result.reason_code == "trade_not_found"
    assert result.action == expected_action
    assert trade_reader.delete_calls == 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("classic_lifecycle_route")
async def test_completed_manual_buy_retry_deduplicates_before_rebuilding_order() -> (
    None
):
    orders = Orders()
    orders.trades = _UnexpectedTradeReader()  # type: ignore[assignment]
    orders.placement_intents = _IntentReader(
        _intent(PlacementIntentState.COMPLETED),
    )  # type: ignore[assignment]

    result = await orders.receive_buy_signal_result(
        "btc-usdc",
        25.0,
        {"dry_run": True},
        operation_id="operation-1",
    )

    assert result.status is OrderMutationStatus.DEDUPLICATED
    assert result.reason_code == "duplicate_operation"
    assert result.operation_id == "operation-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected_status", "expected_reason"),
    [
        (
            PlacementIntentState.COMPLETED,
            OrderMutationStatus.DEDUPLICATED,
            "duplicate_operation",
        ),
        (
            PlacementIntentState.ACCEPTED,
            OrderMutationStatus.INDETERMINATE,
            PlacementIntentState.ACCEPTED.value,
        ),
    ],
)
@pytest.mark.usefixtures("classic_lifecycle_route")
async def test_manual_sell_retry_recovers_intent_after_trade_closes(
    state: PlacementIntentState,
    expected_status: OrderMutationStatus,
    expected_reason: str,
) -> None:
    """A retry must reconcile the durable intent after the trade row is gone."""
    orders = Orders()
    trade_reader = _MissingTradeReader()
    orders.trades = trade_reader  # type: ignore[assignment]
    orders.placement_intents = _IntentReader(_intent(state))  # type: ignore[assignment]

    result = await orders.receive_sell_signal_result(
        "btc-usdc",
        {"dry_run": True},
        operation_id="operator-1",
    )

    assert result.status is expected_status
    assert result.reason_code == expected_reason
    assert result.operation_id == "operator-1"
    assert result.exchange_order_id == "exchange-1"
    assert result.client_order_id == "client-1"
    assert trade_reader.delete_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "expected_action"),
    [
        ("receive_sell_signal_result", "manual_sell"),
        ("receive_buy_signal_result", "manual_buy"),
        ("receive_stop_signal_result", "manual_stop"),
    ],
)
@pytest.mark.usefixtures("classic_lifecycle_route")
async def test_typed_order_result_fails_closed_when_trade_state_is_unavailable(
    method_name: str,
    expected_action: str,
) -> None:
    orders = Orders()
    orders.trades = _UnavailableTradeReader()  # type: ignore[assignment]
    method = getattr(orders, method_name)

    result = (
        await method("btc-usdc", 25.0, {"dry_run": True})
        if expected_action == "manual_buy"
        else await method("btc-usdc", {"dry_run": True})
    )

    assert result.status is OrderMutationStatus.REJECTED
    assert result.reason_code == "trade_state_unavailable"
    assert result.user_message == "Trade state could not be loaded. No order was sent."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "dispatch_name", "expected_action"),
    [
        ("receive_sell_signal_result", "receive_sell_order", "manual_sell"),
        ("receive_buy_signal_result", "receive_buy_order", "manual_buy"),
    ],
)
@pytest.mark.usefixtures("classic_lifecycle_route")
async def test_typed_order_result_reports_applied_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    dispatch_name: str,
    expected_action: str,
) -> None:
    config = {"dry_run": True}
    trade = _trade()
    orders = Orders()
    orders.trades = _TradeReader(trade)  # type: ignore[assignment]
    orders.placement_intents = _IntentReader(None)  # type: ignore[assignment]
    dispatched: list[dict[str, Any]] = []

    async def dispatch(order: dict[str, Any], _config: dict[str, Any]) -> bool:
        dispatched.append(order)
        return True

    monkeypatch.setattr(orders, dispatch_name, dispatch)
    method = getattr(orders, method_name)
    result = (
        await method("btc-usdc", 25.0, config, operation_id="operator-1")
        if expected_action == "manual_buy"
        else await method("btc-usdc", config, operation_id="operator-1")
    )

    assert result.status is OrderMutationStatus.APPLIED
    assert result.operation_id == "operator-1"
    assert dispatched[0]["operation_id"] == "operator-1"
    assert dispatched[0]["lifecycle_snapshot"]["deal_id"] == "deal-1"


@pytest.mark.asyncio
@pytest.mark.usefixtures("classic_lifecycle_route")
async def test_manual_sell_actions_get_distinct_default_operation_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected click must not permanently block a later explicit retry."""
    config = {"dry_run": True}
    trade = _trade()
    orders = Orders()
    orders.trades = _TradeReader(trade)  # type: ignore[assignment]
    orders.placement_intents = _IntentReader(None)  # type: ignore[assignment]
    dispatched: list[dict[str, Any]] = []

    async def reject(order: dict[str, Any], _config: dict[str, Any]) -> bool:
        dispatched.append(order)
        return False

    monkeypatch.setattr(orders, "receive_sell_order", reject)

    first = await orders.receive_sell_signal_result("btc-usdc", config)
    second = await orders.receive_sell_signal_result("btc-usdc", config)

    assert first.operation_id.startswith("manual_sell-")
    assert second.operation_id.startswith("manual_sell-")
    assert first.operation_id != second.operation_id
    assert [order["operation_id"] for order in dispatched] == [
        first.operation_id,
        second.operation_id,
    ]


@pytest.mark.asyncio
@pytest.mark.usefixtures("classic_lifecycle_route")
async def test_typed_stop_result_covers_invalid_missing_applied_and_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = {"dry_run": True}
    orders = Orders()

    invalid = await orders.receive_stop_signal_result("", config)
    orders.trades = _MissingTradeReader()  # type: ignore[assignment]
    missing = await orders.receive_stop_signal_result("btc-usdc", config)

    orders.trades = _TradeReader(_trade())  # type: ignore[assignment]

    async def applied_stop(*_args: Any, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(orders, "receive_stop_signal", applied_stop)
    applied = await orders.receive_stop_signal_result(
        "btc-usdc",
        config,
        operation_id="stop-1",
    )

    orders.trades = _SequenceTradeReader(  # type: ignore[assignment]
        [_trade(), _trade(execution_count=2)]
    )

    async def rejected_stop(*_args: Any, **_kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(orders, "receive_stop_signal", rejected_stop)
    stale = await orders.receive_stop_signal_result("btc-usdc", config)

    assert invalid.reason_code == "invalid_symbol"
    assert missing.reason_code == "trade_not_found"
    assert applied.status is OrderMutationStatus.APPLIED
    assert applied.operation_id == "stop-1"
    assert stale.status is OrderMutationStatus.STALE
