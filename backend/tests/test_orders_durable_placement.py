"""Order-level regression coverage for durable exchange placement."""

from __future__ import annotations

from typing import Any

import model
import pytest
import service.orders as orders_module
from service.capital_budget import CapitalBudgetService
from service.exchange_capabilities import (
    ExchangePostSubmissionFailure,
    ExchangeSubmissionIndeterminate,
)
from service.orders import Orders
from service.placement_intents import (
    PlacementIntentState,
    mark_placements_persisted_in_transaction,
)
from service.placement_reconciliation import PlacementReconciliationSummary
from tortoise import Tortoise
from tortoise.transactions import in_transaction


class _FakeSidestepCampaignService:
    async def resolve_buy_context(
        self,
        _symbol: str,
        _order: dict[str, Any],
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        return {}


class _FakeProactiveExchange:
    def __init__(self, *, indeterminate_cancel: bool = False) -> None:
        self.indeterminate_cancel = indeterminate_cancel
        self.closed = False
        self.cancellations: list[str] = []

    async def place_spot_limit_sell(
        self,
        order: dict[str, Any],
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": "tp-limit-durable-1",
            "symbol": order["symbol"],
            "price": order["limit_price"],
            "amount": order["total_amount"],
        }

    async def cancel_spot_order(
        self,
        _symbol: str,
        order_id: str,
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        self.cancellations.append(order_id)
        if self.indeterminate_cancel:
            raise ExchangeSubmissionIndeterminate(
                action="cancel",
                symbol=_symbol,
                client_order_id=None,
            )
        return {
            "id": order_id,
            "status": "canceled",
            "filled": 0.0,
            "amount": 2.0,
        }

    async def close(self) -> None:
        self.closed = True


class _FakeRejectedSellExchange:
    def __init__(self) -> None:
        self.submissions = 0
        self.closed = False

    async def create_spot_sell(
        self,
        _order: dict[str, Any],
        _config: dict[str, Any],
    ) -> None:
        self.submissions += 1
        return None

    async def close(self) -> None:
        self.closed = True


class _FakeIndeterminateSellExchange(_FakeRejectedSellExchange):
    async def create_spot_sell(
        self,
        order: dict[str, Any],
        _config: dict[str, Any],
    ) -> None:
        self.submissions += 1
        raise ExchangeSubmissionIndeterminate(
            action="market_sell",
            symbol=str(order["symbol"]),
            client_order_id=str(order["client_order_id"]),
        )


class _FakeLimitFallbackExchange:
    def __init__(
        self,
        *,
        indeterminate_market: bool = False,
        partial_market: bool = False,
    ) -> None:
        self.indeterminate_market = indeterminate_market
        self.partial_market = partial_market
        self.limit_client_order_ids: list[str] = []
        self.market_orders: list[dict[str, Any]] = []
        self.closed = False

    async def create_spot_sell(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
        *,
        create_market_fallback,
    ) -> dict[str, Any] | None:
        self.limit_client_order_ids.append(str(order["client_order_id"]))
        return await create_market_fallback(
            dict(order),
            config,
            {
                "requires_market_fallback": True,
                "limit_cancel_confirmed": True,
                "fallback_reason": "limit_order_partial_timeout",
                "exchange_order_id": "limit-exchange-1",
                "symbol": order["symbol"],
                "remaining_amount": 0.6,
                "partial_filled_amount": 0.4,
                "partial_avg_price": 10.5,
            },
        )

    async def create_spot_market_sell(
        self,
        order: dict[str, Any],
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        self.market_orders.append(dict(order))
        if self.indeterminate_market:
            raise ExchangeSubmissionIndeterminate(
                action="market_sell",
                symbol=str(order["symbol"]),
                client_order_id=str(order["client_order_id"]),
            )
        if self.partial_market:
            return {
                "type": "partial_sell",
                "symbol": order["symbol"],
                "partial_filled_amount": 0.6,
                "partial_avg_price": 10.25,
                "partial_proceeds": 6.15,
                "remaining_amount": 0.4,
                "unsellable": False,
                "executions": [],
            }
        return {
            "type": "sold_check",
            "id": "market-exchange-1",
            "symbol": order["symbol"],
            "total_amount": order["total_amount"],
            "timestamp": "1778000001000",
        }

    async def close(self) -> None:
        self.closed = True


class _FakeMissingIdLimitExchange:
    def __init__(self) -> None:
        self.limit_submissions = 0
        self.market_orders: list[dict[str, Any]] = []
        self.closed = False

    async def create_spot_sell(
        self,
        order: dict[str, Any],
        _config: dict[str, Any],
        *,
        create_market_fallback,
    ) -> None:
        del create_market_fallback
        self.limit_submissions += 1
        raise ExchangePostSubmissionFailure(
            action="limit_sell",
            symbol=str(order["symbol"]),
            operation_id=str(order["operation_id"]),
            order={
                **order,
                "status": "open",
            },
            cause=RuntimeError("accepted limit sell returned no order id"),
        )

    async def create_spot_market_sell(
        self,
        order: dict[str, Any],
        _config: dict[str, Any],
    ) -> None:
        self.market_orders.append(dict(order))
        return None

    async def close(self) -> None:
        self.closed = True


def _buy_order(operation_id: str) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "ordersize": 25.0,
        "symbol": "BTC/USDC",
        "direction": "long",
        "botname": "durable_test",
        "baseorder": True,
        "safetyorder": False,
        "order_count": 0,
        "ordertype": "market",
        "so_percentage": None,
        "side": "buy",
    }


def _filled_buy(order: dict[str, Any]) -> dict[str, Any]:
    return {
        **order,
        "timestamp": "1778000000000",
        "fees": 0.001,
        "precision": 8,
        "amount_fee": 0.0,
        "amount": 0.001,
        "price": 25000.0,
        "orderid": "exchange-buy-1",
        "id": "exchange-buy-1",
    }


async def _init_database(tmp_path) -> None:
    database_path = tmp_path / "orders-durable-placement.sqlite"
    await Tortoise.init(
        db_url=f"sqlite://{database_path}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()


@pytest.mark.asyncio
async def test_orders_reconciliation_uses_recovery_handler_and_closes_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = PlacementReconciliationSummary(
        inspected=0,
        completed=0,
        rejected=0,
        quarantined=0,
        ready=True,
        action_required=(),
    )
    callback_names: list[str] = []

    class _FakeReconciler:
        def __init__(self, _exchange, resume, _intents) -> None:
            callback_names.append(resume.__name__)

        async def reconcile(self, _config) -> PlacementReconciliationSummary:
            return summary

    class _FakeCloseExchange:
        closed = False

        async def close(self) -> None:
            self.closed = True

    orders = Orders()
    exchange = _FakeCloseExchange()
    orders.exchange = exchange  # type: ignore[assignment]
    monkeypatch.setattr(orders_module, "PlacementReconciler", _FakeReconciler)

    result = await orders.reconcile_placement_intents({})

    assert result is summary
    assert callback_names == ["resume"]
    assert exchange.closed is True


@pytest.mark.asyncio
async def test_filled_buy_is_persisted_once_and_duplicate_is_deduplicated(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_database(tmp_path)
    CapitalBudgetService._leases.clear()
    try:
        orders = Orders()
        orders.sidestep_campaigns = _FakeSidestepCampaignService()
        submissions: list[dict[str, Any]] = []

        async def create_spot_market_buy(
            order: dict[str, Any],
            _config: dict[str, Any],
        ) -> dict[str, Any]:
            submissions.append(dict(order))
            return _filled_buy(order)

        monkeypatch.setattr(
            orders.exchange,
            "create_spot_market_buy",
            create_spot_market_buy,
        )
        order = _buy_order("buy-once")
        config = {"exchange": "binance", "dry_run": False}

        first, first_precheck = await orders._execute_budgeted_buy_order(
            order,
            config,
        )
        second, second_precheck = await orders._execute_budgeted_buy_order(
            order,
            config,
        )

        assert first is True
        assert first_precheck is None
        assert second is True
        assert second_precheck is None
        assert len(submissions) == 1
        assert submissions[0]["client_order_id"].startswith("mw-")
        assert await model.Trades.filter(orderid="exchange-buy-1").count() == 1
        intent = await model.PlacementIntent.get(operation_id="buy-once")
        assert intent.state == PlacementIntentState.COMPLETED.value
        assert intent.exchange_order_id == "exchange-buy-1"
    finally:
        CapitalBudgetService._leases.clear()
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_lost_buy_response_is_retained_without_blind_retry(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_database(tmp_path)
    CapitalBudgetService._leases.clear()
    try:
        orders = Orders()

        async def create_spot_market_buy(
            order: dict[str, Any],
            _config: dict[str, Any],
        ) -> None:
            raise ExchangeSubmissionIndeterminate(
                action="buy",
                symbol=str(order["symbol"]),
                client_order_id=str(order["client_order_id"]),
            )

        monkeypatch.setattr(
            orders.exchange,
            "create_spot_market_buy",
            create_spot_market_buy,
        )
        order = _buy_order("buy-indeterminate")
        result, precheck = await orders._execute_budgeted_buy_order(
            order,
            {"exchange": "binance", "dry_run": False},
        )

        assert result is False
        assert precheck is not None
        assert precheck["reason"] == "placement_indeterminate"
        intent = await model.PlacementIntent.get(operation_id="buy-indeterminate")
        assert intent.state == PlacementIntentState.INDETERMINATE.value
        assert intent.reason_code == "exchange_response_lost"
        assert await model.Trades.all().count() == 0
    finally:
        CapitalBudgetService._leases.clear()
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_accepted_buy_finalization_failure_blocks_new_ticker_submission(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_database(tmp_path)
    CapitalBudgetService._leases.clear()
    try:
        orders = Orders()
        submissions = 0

        async def accepted_then_failed(
            order: dict[str, Any],
            _config: dict[str, Any],
        ) -> None:
            nonlocal submissions
            submissions += 1
            raise ExchangePostSubmissionFailure(
                action="buy",
                symbol=str(order["symbol"]),
                operation_id=str(order["operation_id"]),
                order={
                    **order,
                    "id": "exchange-accepted-buy",
                    "status": "closed",
                },
                cause=RuntimeError("trade lookup unavailable"),
            )

        monkeypatch.setattr(
            orders.exchange,
            "create_spot_market_buy",
            accepted_then_failed,
        )
        config = {"exchange": "binance", "dry_run": False}

        first, first_precheck = await orders._execute_budgeted_buy_order(
            _buy_order("buy-accepted-first"),
            config,
        )
        second, second_precheck = await orders._execute_budgeted_buy_order(
            _buy_order("buy-fresh-ticker"),
            config,
        )

        assert first is False
        assert first_precheck is not None
        assert first_precheck["reason"] == "placement_reconciliation_pending"
        assert second is False
        assert second_precheck is not None
        assert second_precheck["reason"] == "placement_accepted"
        assert submissions == 1
        intent = await model.PlacementIntent.get(operation_id="buy-accepted-first")
        assert intent.state == PlacementIntentState.ACCEPTED.value
        assert intent.exchange_order_id == "exchange-accepted-buy"
        assert await model.PlacementIntent.all().count() == 1
    finally:
        CapitalBudgetService._leases.clear()
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_definitive_buy_failure_is_rejected_and_can_use_new_operation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_database(tmp_path)
    CapitalBudgetService._leases.clear()
    try:
        orders = Orders()

        async def reject_buy(
            _order: dict[str, Any],
            _config: dict[str, Any],
        ) -> None:
            orders.exchange._last_buy_precheck_result = {
                "ok": False,
                "reason": "insufficient_quote_balance",
            }
            return None

        monkeypatch.setattr(orders.exchange, "create_spot_market_buy", reject_buy)
        result, precheck = await orders._execute_budgeted_buy_order(
            _buy_order("buy-rejected"),
            {"exchange": "binance", "dry_run": False},
        )

        assert result is False
        assert precheck is not None
        assert precheck["reason"] == "insufficient_quote_balance"
        intent = await model.PlacementIntent.get(operation_id="buy-rejected")
        assert intent.state == PlacementIntentState.REJECTED.value
        assert intent.reason_code == "insufficient_quote_balance"
    finally:
        CapitalBudgetService._leases.clear()
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_proactive_limit_placement_persists_intent_and_trade_metadata(
    tmp_path,
) -> None:
    await _init_database(tmp_path)
    try:
        await model.OpenTrades.create(symbol="XPL/USDC")
        orders = Orders()
        fake_exchange = _FakeProactiveExchange()
        orders.exchange = fake_exchange  # type: ignore[assignment]

        armed = await orders.arm_tp_limit_order(
            {
                "operation_id": "durable-tp-arm",
                "symbol": "XPL/USDC",
                "total_amount": 2.0,
                "limit_price": 11.0,
            },
            {"exchange": "binance", "dry_run": False},
        )

        assert armed is True
        open_trade = await model.OpenTrades.get(symbol="XPL/USDC")
        assert open_trade.tp_limit_order_id == "tp-limit-durable-1"
        intent = await model.PlacementIntent.get(operation_id="durable-tp-arm")
        assert intent.state == PlacementIntentState.COMPLETED.value
        assert intent.exchange_order_id == "tp-limit-durable-1"
        assert fake_exchange.closed is True
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_proactive_limit_lost_response_stays_indeterminate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_database(tmp_path)
    try:
        await model.OpenTrades.create(symbol="LOST/USDC")
        orders = Orders()
        fake_exchange = _FakeProactiveExchange()

        async def lose_response(
            order: dict[str, Any],
            _config: dict[str, Any],
        ) -> None:
            raise ExchangeSubmissionIndeterminate(
                action="limit_sell",
                symbol=str(order["symbol"]),
                client_order_id=str(order["client_order_id"]),
            )

        monkeypatch.setattr(fake_exchange, "place_spot_limit_sell", lose_response)
        orders.exchange = fake_exchange  # type: ignore[assignment]

        order = {
            "operation_id": "durable-tp-lost",
            "symbol": "LOST/USDC",
            "total_amount": 2.0,
            "limit_price": 11.0,
        }
        config = {"exchange": "binance", "dry_run": False}
        armed = await orders.arm_tp_limit_order(order, config)
        duplicate = await orders.arm_tp_limit_order(order, config)

        assert armed is False
        assert duplicate is False
        intent = await model.PlacementIntent.get(operation_id="durable-tp-lost")
        assert intent.state == PlacementIntentState.INDETERMINATE.value
        assert intent.reason_code == "exchange_response_lost"
        assert fake_exchange.closed is True
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_proactive_limit_definitive_failure_is_rejected(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_database(tmp_path)
    try:
        await model.OpenTrades.create(symbol="REJECT/USDC")
        orders = Orders()
        fake_exchange = _FakeProactiveExchange()

        async def reject_order(
            _order: dict[str, Any],
            _config: dict[str, Any],
        ) -> None:
            return None

        monkeypatch.setattr(fake_exchange, "place_spot_limit_sell", reject_order)
        orders.exchange = fake_exchange  # type: ignore[assignment]

        armed = await orders.arm_tp_limit_order(
            {
                "operation_id": "durable-tp-rejected",
                "symbol": "REJECT/USDC",
                "total_amount": 2.0,
                "limit_price": 11.0,
            },
            {"exchange": "binance", "dry_run": False},
        )

        assert armed is False
        intent = await model.PlacementIntent.get(operation_id="durable-tp-rejected")
        assert intent.state == PlacementIntentState.REJECTED.value
        assert intent.reason_code == "limit_order_not_placed"
        assert fake_exchange.closed is True
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_proactive_limit_persistence_failure_uses_durable_cancel_child(
    tmp_path,
) -> None:
    await _init_database(tmp_path)
    try:
        orders = Orders()
        fake_exchange = _FakeProactiveExchange()
        orders.exchange = fake_exchange  # type: ignore[assignment]

        armed = await orders.arm_tp_limit_order(
            {
                "operation_id": "durable-tp-persist-failure",
                "symbol": "MISSING/USDC",
                "total_amount": 2.0,
                "limit_price": 11.0,
            },
            {"exchange": "binance", "dry_run": False},
        )

        assert armed is False
        intents = await model.PlacementIntent.all().order_by("created_at")
        assert len(intents) == 2
        parent, cancellation = intents
        assert parent.operation_id == "durable-tp-persist-failure"
        assert parent.state == PlacementIntentState.QUARANTINED.value
        assert parent.reason_code == "limit_metadata_persistence_failed_compensated"
        assert cancellation.source_operation_id == parent.operation_id
        assert cancellation.action == "cancel"
        assert cancellation.exchange_order_id == "tp-limit-durable-1"
        assert cancellation.state == PlacementIntentState.COMPLETED.value
        assert fake_exchange.cancellations == ["tp-limit-durable-1"]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_lost_compensation_response_is_not_submitted_twice(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        orders = Orders()
        fake_exchange = _FakeProactiveExchange(indeterminate_cancel=True)
        orders.exchange = fake_exchange  # type: ignore[assignment]
        order = {
            "operation_id": "durable-tp-cancel-lost",
            "symbol": "MISSING/USDC",
            "total_amount": 2.0,
            "limit_price": 11.0,
        }
        config = {"exchange": "binance", "dry_run": False}

        armed = await orders.arm_tp_limit_order(order, config)
        duplicate = await orders.arm_tp_limit_order(order, config)

        assert armed is False
        assert duplicate is False
        intents = await model.PlacementIntent.all().order_by("created_at")
        assert len(intents) == 2
        parent, cancellation = intents
        assert parent.state == PlacementIntentState.QUARANTINED.value
        assert parent.reason_code == "limit_persistence_and_cancel_uncertain"
        assert cancellation.source_operation_id == parent.operation_id
        assert cancellation.state == PlacementIntentState.INDETERMINATE.value
        assert cancellation.reason_code == "cancel_response_lost"
        assert fake_exchange.cancellations == ["tp-limit-durable-1"]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_definitive_sell_rejection_is_durable_and_not_retried(
    tmp_path,
) -> None:
    await _init_database(tmp_path)
    try:
        await model.Trades.create(
            timestamp="1778000000000",
            ordersize=10.0,
            fee=0.0,
            precision=8,
            amount=1.0,
            amount_fee=0.0,
            price=10.0,
            symbol="ETH/USDC",
            orderid="buy-before-sell",
            bot="durable_test",
            ordertype="market",
            baseorder=True,
            safetyorder=False,
            order_count=0,
            so_percentage=None,
            direction="long",
            side="buy",
        )
        await model.OpenTrades.create(symbol="ETH/USDC")
        orders = Orders()
        fake_exchange = _FakeRejectedSellExchange()
        orders.exchange = fake_exchange  # type: ignore[assignment]
        sell_order = {
            "operation_id": "durable-sell-rejected",
            "symbol": "ETH/USDC",
            "direction": "long",
            "side": "sell",
            "type_sell": "order_sell",
            "actual_pnl": 0.0,
            "total_cost": 10.0,
            "current_price": 10.0,
            "sell_reason": "manual_sell",
            "skip_tp_limit_cancel": True,
        }
        config = {"exchange": "binance", "dry_run": False}

        await orders.receive_sell_order(sell_order, config)
        await orders.receive_sell_order(sell_order, config)

        assert fake_exchange.submissions == 1
        assert fake_exchange.closed is True
        intent = await model.PlacementIntent.get(operation_id="durable-sell-rejected")
        assert intent.state == PlacementIntentState.REJECTED.value
        assert intent.reason_code == "exchange_rejected_or_unfilled"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_lost_sell_response_stays_indeterminate(
    tmp_path,
) -> None:
    await _init_database(tmp_path)
    try:
        await model.Trades.create(
            timestamp="1778000000000",
            ordersize=10.0,
            fee=0.0,
            precision=8,
            amount=1.0,
            amount_fee=0.0,
            price=10.0,
            symbol="SOL/USDC",
            orderid="buy-before-lost-sell",
            bot="durable_test",
            ordertype="market",
            baseorder=True,
            safetyorder=False,
            order_count=0,
            so_percentage=None,
            direction="long",
            side="buy",
        )
        await model.OpenTrades.create(symbol="SOL/USDC")
        orders = Orders()
        fake_exchange = _FakeIndeterminateSellExchange()
        orders.exchange = fake_exchange  # type: ignore[assignment]

        await orders.receive_sell_order(
            {
                "operation_id": "durable-sell-lost",
                "symbol": "SOL/USDC",
                "direction": "long",
                "side": "sell",
                "type_sell": "order_sell",
                "actual_pnl": 0.0,
                "total_cost": 10.0,
                "current_price": 10.0,
                "sell_reason": "manual_sell",
                "skip_tp_limit_cancel": True,
            },
            {"exchange": "binance", "dry_run": False},
        )

        assert fake_exchange.submissions == 1
        intent = await model.PlacementIntent.get(operation_id="durable-sell-lost")
        assert intent.state == PlacementIntentState.INDETERMINATE.value
        assert intent.reason_code == "exchange_response_lost"
        assert fake_exchange.closed is True
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_filled_sell_advances_through_atomic_persistence(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_database(tmp_path)
    try:
        await model.Trades.create(
            timestamp="1778000000000",
            ordersize=10.0,
            fee=0.0,
            precision=8,
            amount=1.0,
            amount_fee=0.0,
            price=10.0,
            symbol="ADA/USDC",
            orderid="buy-before-filled-sell",
            bot="durable_test",
            ordertype="market",
            baseorder=True,
            safetyorder=False,
            order_count=0,
            so_percentage=None,
            direction="long",
            side="buy",
        )
        await model.OpenTrades.create(symbol="ADA/USDC")
        orders = Orders()
        fake_exchange = _FakeRejectedSellExchange()

        async def filled_sell(
            order: dict[str, Any],
            _config: dict[str, Any],
        ) -> dict[str, Any]:
            fake_exchange.submissions += 1
            return {
                "type": "sold_check",
                "id": "filled-sell-1",
                "symbol": order["symbol"],
                "total_amount": order["total_amount"],
                "timestamp": "1778000001000",
            }

        async def persist_sell(
            _status: dict[str, Any],
            _config: dict[str, Any],
            *,
            placement_operation_id: str | None = None,
        ) -> None:
            await orders.placement_intents.transition(
                placement_operation_id,
                PlacementIntentState.PERSISTED,
            )

        monkeypatch.setattr(fake_exchange, "create_spot_sell", filled_sell)
        monkeypatch.setattr(orders, "_finalize_completed_sell", persist_sell)
        orders.exchange = fake_exchange  # type: ignore[assignment]

        await orders.receive_sell_order(
            {
                "operation_id": "durable-sell-filled",
                "symbol": "ADA/USDC",
                "direction": "long",
                "side": "sell",
                "type_sell": "order_sell",
                "actual_pnl": 0.0,
                "total_cost": 10.0,
                "current_price": 11.0,
                "sell_reason": "manual_sell",
                "campaign_id": "campaign-1",
                "skip_tp_limit_cancel": True,
            },
            {"exchange": "binance", "dry_run": False},
        )

        intent = await model.PlacementIntent.get(operation_id="durable-sell-filled")
        assert intent.state == PlacementIntentState.COMPLETED.value
        assert intent.exchange_order_id == "filled-sell-1"
        assert fake_exchange.submissions == 1
        assert fake_exchange.closed is True
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_limit_fallback_uses_distinct_durable_child_identity(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_database(tmp_path)
    try:
        await model.Trades.create(
            timestamp="1778000000000",
            ordersize=10.0,
            fee=0.0,
            precision=8,
            amount=1.0,
            amount_fee=0.0,
            price=10.0,
            symbol="LINK/USDC",
            orderid="buy-before-fallback",
            bot="durable_test",
            ordertype="market",
            baseorder=True,
            safetyorder=False,
            order_count=0,
            so_percentage=None,
            direction="long",
            side="buy",
        )
        await model.OpenTrades.create(symbol="LINK/USDC")
        orders = Orders()
        fake_exchange = _FakeLimitFallbackExchange()
        orders.exchange = fake_exchange  # type: ignore[assignment]

        async def persist_sell(
            _status: dict[str, Any],
            _config: dict[str, Any],
            *,
            placement_operation_ids: list[str] | None = None,
        ) -> None:
            async with in_transaction() as connection:
                await mark_placements_persisted_in_transaction(
                    list(placement_operation_ids or []),
                    connection,
                )

        monkeypatch.setattr(orders, "_finalize_completed_sell", persist_sell)
        await orders.receive_sell_order(
            {
                "operation_id": "durable-limit-parent",
                "symbol": "LINK/USDC",
                "direction": "long",
                "side": "sell",
                "type_sell": "order_sell",
                "actual_pnl": 0.0,
                "total_cost": 10.0,
                "current_price": 10.5,
                "sell_reason": "manual_sell",
                "skip_tp_limit_cancel": True,
            },
            {
                "exchange": "binance",
                "dry_run": False,
                "sell_order_type": "limit",
            },
        )

        intents = await model.PlacementIntent.all().order_by("created_at")
        assert len(intents) == 2
        parent, child = intents
        assert parent.operation_id == "durable-limit-parent"
        assert parent.action == "limit_sell"
        assert parent.state == PlacementIntentState.COMPLETED.value
        assert parent.exchange_order_id == "limit-exchange-1"
        assert child.source_operation_id == parent.operation_id
        assert child.action == "sell"
        assert child.order_type == "market"
        assert child.state == PlacementIntentState.COMPLETED.value
        assert child.client_order_id != parent.client_order_id
        assert fake_exchange.market_orders[0]["client_order_id"] == (
            child.client_order_id
        )
        assert fake_exchange.limit_client_order_ids == [parent.client_order_id]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_limit_sell_missing_id_does_not_submit_market_fallback(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        await model.Trades.create(
            timestamp="1778000000000",
            ordersize=10.0,
            fee=0.0,
            precision=8,
            amount=1.0,
            amount_fee=0.0,
            price=10.0,
            symbol="NEAR/USDC",
            orderid="buy-before-missing-id-sell",
            bot="durable_test",
            ordertype="market",
            baseorder=True,
            safetyorder=False,
            order_count=0,
            so_percentage=None,
            direction="long",
            side="buy",
        )
        await model.OpenTrades.create(symbol="NEAR/USDC")
        orders = Orders()
        fake_exchange = _FakeMissingIdLimitExchange()
        orders.exchange = fake_exchange  # type: ignore[assignment]

        await orders.receive_sell_order(
            {
                "operation_id": "durable-limit-missing-id",
                "symbol": "NEAR/USDC",
                "direction": "long",
                "side": "sell",
                "type_sell": "order_sell",
                "actual_pnl": 0.0,
                "total_cost": 10.0,
                "current_price": 10.5,
                "sell_reason": "manual_sell",
                "skip_tp_limit_cancel": True,
            },
            {
                "exchange": "binance",
                "dry_run": False,
                "sell_order_type": "limit",
            },
        )

        intent = await model.PlacementIntent.get(
            operation_id="durable-limit-missing-id"
        )
        assert intent.state == PlacementIntentState.ACCEPTED.value
        assert intent.reason_code == "local_finalization_pending"
        assert fake_exchange.limit_submissions == 1
        assert fake_exchange.market_orders == []
        assert await model.PlacementIntent.all().count() == 1
        assert fake_exchange.closed is True
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_indeterminate_market_fallback_blocks_parent_retry(
    tmp_path,
) -> None:
    await _init_database(tmp_path)
    try:
        await model.Trades.create(
            timestamp="1778000000000",
            ordersize=10.0,
            fee=0.0,
            precision=8,
            amount=1.0,
            amount_fee=0.0,
            price=10.0,
            symbol="AVAX/USDC",
            orderid="buy-before-fallback-loss",
            bot="durable_test",
            ordertype="market",
            baseorder=True,
            safetyorder=False,
            order_count=0,
            so_percentage=None,
            direction="long",
            side="buy",
        )
        await model.OpenTrades.create(symbol="AVAX/USDC")
        orders = Orders()
        fake_exchange = _FakeLimitFallbackExchange(indeterminate_market=True)
        orders.exchange = fake_exchange  # type: ignore[assignment]
        sell_order = {
            "operation_id": "durable-limit-loss",
            "symbol": "AVAX/USDC",
            "direction": "long",
            "side": "sell",
            "type_sell": "order_sell",
            "actual_pnl": 0.0,
            "total_cost": 10.0,
            "current_price": 10.5,
            "sell_reason": "manual_sell",
            "skip_tp_limit_cancel": True,
        }
        config = {
            "exchange": "binance",
            "dry_run": False,
            "sell_order_type": "limit",
        }

        await orders.receive_sell_order(sell_order, config)
        await orders.receive_sell_order(sell_order, config)

        intents = await model.PlacementIntent.all().order_by("created_at")
        assert len(intents) == 2
        parent, child = intents
        assert parent.state == PlacementIntentState.FILLED.value
        assert child.state == PlacementIntentState.INDETERMINATE.value
        assert child.source_operation_id == parent.operation_id
        assert child.client_order_id != parent.client_order_id
        assert len(fake_exchange.limit_client_order_ids) == 1
        assert len(fake_exchange.market_orders) == 1
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_partial_market_fallback_persists_both_placement_legs(
    tmp_path,
) -> None:
    await _init_database(tmp_path)
    try:
        await model.Trades.create(
            timestamp="1778000000000",
            ordersize=10.0,
            fee=0.0,
            precision=8,
            amount=1.0,
            amount_fee=0.0,
            price=10.0,
            symbol="ATOM/USDC",
            orderid="buy-before-partial-fallback",
            bot="durable_test",
            ordertype="market",
            baseorder=True,
            safetyorder=False,
            order_count=0,
            so_percentage=None,
            direction="long",
            side="buy",
        )
        await model.OpenTrades.create(symbol="ATOM/USDC")
        orders = Orders()
        orders.exchange = _FakeLimitFallbackExchange(  # type: ignore[assignment]
            partial_market=True
        )

        await orders.receive_sell_order(
            {
                "operation_id": "durable-limit-partial",
                "symbol": "ATOM/USDC",
                "direction": "long",
                "side": "sell",
                "type_sell": "order_sell",
                "actual_pnl": 0.0,
                "total_cost": 10.0,
                "current_price": 10.5,
                "sell_reason": "manual_sell",
                "skip_tp_limit_cancel": True,
            },
            {
                "exchange": "binance",
                "dry_run": False,
                "sell_order_type": "limit",
            },
        )

        intents = await model.PlacementIntent.all().order_by("created_at")
        assert [intent.state for intent in intents] == [
            PlacementIntentState.COMPLETED.value,
            PlacementIntentState.COMPLETED.value,
        ]
        open_trade = await model.OpenTrades.get(symbol="ATOM/USDC")
        assert open_trade.sold_amount == pytest.approx(0.6)
        assert open_trade.sold_proceeds == pytest.approx(6.15)
    finally:
        await Tortoise.close_connections()
