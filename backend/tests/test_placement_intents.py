"""Regression coverage for crash-safe exchange placement intents."""

from __future__ import annotations

import json

import model
import pytest
from service.capital_budget import CapitalBudgetService
from service.placement_intents import (
    PlacementAction,
    PlacementIntentService,
    PlacementIntentState,
    mark_placement_persisted_in_transaction,
)
from service.placement_workflow import PlacementStartStatus, PlacementWorkflow
from tortoise import Tortoise
from tortoise.transactions import in_transaction


async def _init_database(tmp_path) -> None:
    database_path = tmp_path / "placement-intents.sqlite"
    await Tortoise.init(
        db_url=f"sqlite://{database_path}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()


@pytest.mark.asyncio
async def test_prepare_claim_is_durable_sanitized_and_single_owner(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        config = {"exchange": "binance", "dry_run": False}
        order = {
            "operation_id": "buy-operation-1",
            "symbol": "BTC/USDC",
            "side": "buy",
            "ordertype": "market",
            "ordersize": 25.0,
            "api_key": "must-not-be-persisted",
            "secret": "must-not-be-persisted",
        }

        first = await service.prepare(
            order,
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="market",
            requested_quote=25.0,
            reserved_quote=25.0,
        )
        duplicate = await service.prepare(
            dict(order),
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="market",
            requested_quote=25.0,
            reserved_quote=25.0,
        )

        assert first.operation_id == "buy-operation-1"
        assert first.client_order_id == duplicate.client_order_id
        assert first.client_order_id is not None
        assert len(first.client_order_id) <= 36
        assert await service.claim_submission(first.operation_id) is True
        assert await service.claim_submission(duplicate.operation_id) is False

        persisted = await model.PlacementIntent.get(operation_id="buy-operation-1")
        request_payload = json.loads(persisted.request_json)
        assert request_payload["symbol"] == "BTC/USDC"
        assert "api_key" not in request_payload
        assert "secret" not in request_payload
        assert persisted.state == PlacementIntentState.SUBMITTING.value
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_fill_and_business_persistence_advance_monotonically(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        preparation = await service.prepare(
            {
                "operation_id": "sell-operation-1",
                "symbol": "ETH/USDC",
                "total_amount": 1.0,
            },
            {"exchange": "binance", "dry_run": False},
            action=PlacementAction.SELL,
            side="sell",
            order_type="market",
            requested_amount=1.0,
        )

        assert await service.claim_submission(preparation.operation_id) is True
        await service.transition(
            preparation.operation_id,
            PlacementIntentState.FILLED,
            exchange_order_id="exchange-order-1",
            result={"status": "closed", "filled": 1.0},
        )
        async with in_transaction() as connection:
            await mark_placement_persisted_in_transaction(
                preparation.operation_id,
                connection,
            )
        await service.transition(
            preparation.operation_id,
            PlacementIntentState.COMPLETED,
        )

        persisted = await model.PlacementIntent.get(operation_id="sell-operation-1")
        assert persisted.state == PlacementIntentState.COMPLETED.value
        assert persisted.exchange_order_id == "exchange-order-1"
        assert json.loads(persisted.result_json)["filled"] == 1.0
        assert persisted.completed_at is not None
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_invalid_transition_and_operation_id_reuse_fail_closed(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        config = {"exchange": "binance", "dry_run": False}
        preparation = await service.prepare(
            {"operation_id": "shared-operation", "symbol": "BTC/USDC"},
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="market",
        )

        with pytest.raises(ValueError, match="Invalid placement transition"):
            await service.transition(
                preparation.operation_id,
                PlacementIntentState.COMPLETED,
            )
        with pytest.raises(ValueError, match="reused with a different request"):
            await service.prepare(
                {"operation_id": "shared-operation", "symbol": "ETH/USDC"},
                config,
                action=PlacementAction.BUY,
                side="buy",
                order_type="market",
            )
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_indeterminate_buy_reservation_survives_process_lease(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        preparation = await service.prepare(
            {
                "operation_id": "reserved-buy",
                "symbol": "BTC/USDC",
                "ordersize": 30.0,
            },
            {"exchange": "binance", "dry_run": False},
            action=PlacementAction.BUY,
            side="buy",
            order_type="market",
            requested_quote=30.0,
            reserved_quote=30.0,
        )
        assert await service.claim_submission(preparation.operation_id) is True
        await service.transition(
            preparation.operation_id,
            PlacementIntentState.INDETERMINATE,
            reason_code="response_lost",
        )

        CapitalBudgetService._leases.clear()
        runtime_state = await CapitalBudgetService().get_runtime_state(
            {
                "capital_max_fund": 100.0,
                "capital_reserve_safety_orders": False,
                "capital_budget_buffer_pct": 0.0,
            }
        )

        assert runtime_state["capital_pending_quote"] == pytest.approx(30.0)
        assert runtime_state["capital_available_quote"] == pytest.approx(70.0)
    finally:
        CapitalBudgetService._leases.clear()
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_dry_run_does_not_require_a_durable_exchange_intent() -> None:
    preparation = await PlacementIntentService().prepare(
        {"symbol": "BTC/USDC"},
        {"exchange": "binance", "dry_run": True},
        action=PlacementAction.BUY,
        side="buy",
        order_type="market",
    )

    assert preparation.intent is None
    assert preparation.operation_id is None


@pytest.mark.asyncio
async def test_new_operation_reuses_pending_symbol_action(tmp_path) -> None:
    """A fresh ticker identity must not bypass an accepted pending buy."""
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        config = {"exchange": "binance", "dry_run": False}
        first_order = {
            "operation_id": "buy-pending-first",
            "symbol": "BTC/USDC",
        }
        first = await service.prepare(
            first_order,
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="market",
        )
        assert await service.claim_submission(first.operation_id) is True
        await service.transition(
            first.operation_id,
            PlacementIntentState.ACCEPTED,
            exchange_order_id="exchange-buy-pending",
        )

        next_order = {
            "operation_id": "buy-new-ticker-identity",
            "symbol": "BTC/USDC",
        }
        reused = await service.prepare(
            next_order,
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="market",
        )

        assert reused.operation_id == "buy-pending-first"
        assert next_order["operation_id"] == "buy-new-ticker-identity"
        assert reused.blocked_by_conflict is True
        assert await model.PlacementIntent.all().count() == 1
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first_action", "next_action", "first_side", "next_side"),
    [
        (
            PlacementAction.SELL,
            PlacementAction.LIMIT_SELL,
            "sell",
            "sell",
        ),
        (
            PlacementAction.BUY,
            PlacementAction.SELL,
            "buy",
            "sell",
        ),
    ],
)
async def test_pending_exposure_blocks_other_action_types(
    tmp_path,
    first_action: PlacementAction,
    next_action: PlacementAction,
    first_side: str,
    next_side: str,
) -> None:
    """Hot-reloaded execution modes must not bypass a pending symbol barrier."""
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        config = {"exchange": "binance", "dry_run": False}
        first_order = {
            "operation_id": f"{first_action}-pending",
            "symbol": "BTC/USDC",
        }
        first = await service.prepare(
            first_order,
            config,
            action=first_action,
            side=first_side,
            order_type="market",
        )
        assert await service.claim_submission(first.operation_id) is True
        await service.transition(
            first.operation_id,
            PlacementIntentState.ACCEPTED,
            exchange_order_id="exchange-pending",
        )

        next_order = {
            "operation_id": f"{next_action}-fresh",
            "symbol": "BTC/USDC",
        }
        blocked = await service.prepare(
            next_order,
            config,
            action=next_action,
            side=next_side,
            order_type=(
                "limit" if next_action == PlacementAction.LIMIT_SELL else "market"
            ),
        )

        assert blocked.operation_id == first.operation_id
        assert next_order["operation_id"] == f"{next_action}-fresh"
        assert blocked.blocked_by_conflict is True
        assert await model.PlacementIntent.all().count() == 1
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_prepared_cross_action_conflict_cannot_be_claimed(tmp_path) -> None:
    """A caller for another action must never claim the prepared blocker."""
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        workflow = PlacementWorkflow(service)
        config = {"exchange": "binance", "dry_run": False}
        first = await service.prepare(
            {
                "operation_id": "prepared-buy",
                "symbol": "BTC/USDC",
            },
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="market",
        )
        next_order = {
            "operation_id": "fresh-sell",
            "symbol": "BTC/USDC",
        }

        blocked = await workflow.begin(
            next_order,
            config,
            action=PlacementAction.SELL,
            side="sell",
            order_type="market",
        )

        assert blocked.status == PlacementStartStatus.BLOCKED
        assert blocked.operation_id == first.operation_id
        assert next_order["operation_id"] == "fresh-sell"
        persisted = await model.PlacementIntent.get(operation_id="prepared-buy")
        assert persisted.state == PlacementIntentState.PREPARED.value
        assert await model.PlacementIntent.all().count() == 1
    finally:
        await Tortoise.close_connections()
