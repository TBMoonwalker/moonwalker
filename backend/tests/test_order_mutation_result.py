"""Typed operator mutation result mapping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from service.lifecycle_snapshot import LifecycleSnapshotIdentity
from service.order_mutation_result import (
    OrderMutationResult,
    OrderMutationStatus,
)
from service.orders import Orders
from service.placement_intents import PlacementIntentState
from service.trades import TradeStateUnavailableError


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

    async def delete_open_trades(self, _symbol: str) -> None:
        return None


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
@pytest.mark.parametrize(
    ("method_name", "expected_action"),
    [
        ("receive_sell_signal_result", "manual_sell"),
        ("receive_buy_signal_result", "manual_buy"),
        ("receive_stop_signal_result", "manual_stop"),
    ],
)
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
