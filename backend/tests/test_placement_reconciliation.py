"""Regression coverage for fail-closed placement reconciliation."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

import model
import pytest
from service.exchange_capabilities import (
    ExchangeOrderLookupResult,
    ExchangeOrderLookupStatus,
)
from service.placement_intents import (
    PlacementAction,
    PlacementIntentService,
    PlacementIntentState,
)
from service.placement_reconciliation import PlacementReconciler
from tortoise import Tortoise


async def _init_database(tmp_path) -> None:
    database_path = tmp_path / "placement-reconciliation.sqlite"
    await Tortoise.init(
        db_url=f"sqlite://{database_path}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()


class _FakeExchange:
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


async def _prepare_live_intent(
    service: PlacementIntentService,
    operation_id: str,
) -> Any:
    return await service.prepare(
        {
            "operation_id": operation_id,
            "symbol": "BTC/USDC",
            "total_amount": 1.0,
        },
        {"exchange": "binance", "market": "spot", "dry_run": False},
        action=PlacementAction.SELL,
        side="sell",
        order_type="market",
        requested_amount=1.0,
    )


def _reject_resume(*_args: Any) -> Awaitable[bool]:
    raise AssertionError("local persistence must not run")


@pytest.mark.asyncio
async def test_prepared_intent_is_rejected_without_exchange_lookup(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        preparation = await _prepare_live_intent(service, "prepared-sell")
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
        )

        summary = await PlacementReconciler(
            exchange,
            _reject_resume,
            service,
        ).reconcile({"exchange": "binance", "market": "spot", "dry_run": False})

        intent = await service.get(str(preparation.operation_id))
        assert intent.state == PlacementIntentState.REJECTED.value
        assert intent.reason_code == "startup_confirmed_never_submitted"
        assert exchange.calls == []
        assert summary.ready is True
        assert summary.rejected == 1
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_submitting_intent_is_rejected_only_after_typed_not_found(
    tmp_path,
) -> None:
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        preparation = await _prepare_live_intent(service, "missing-sell")
        assert await service.claim_submission(preparation.operation_id) is True
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.NOT_FOUND,
                error_message="order does not exist",
            )
        )

        summary = await PlacementReconciler(
            exchange,
            _reject_resume,
            service,
        ).reconcile({"exchange": "binance", "market": "spot", "dry_run": False})

        intent = await service.get(str(preparation.operation_id))
        assert intent.state == PlacementIntentState.REJECTED.value
        assert intent.reason_code == "exchange_identity_not_found"
        assert intent.reconciliation_attempts == 1
        assert exchange.calls[0]["client_order_id"] == preparation.client_order_id
        assert summary.ready is True
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_indeterminate_filled_intent_resumes_persistence_once(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        preparation = await _prepare_live_intent(service, "filled-sell")
        assert await service.claim_submission(preparation.operation_id) is True
        await service.transition(
            preparation.operation_id,
            PlacementIntentState.INDETERMINATE,
            reason_code="response_lost",
        )
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={
                    "id": "exchange-sell-1",
                    "status": "closed",
                    "filled": 1.0,
                    "amount": 1.0,
                },
            )
        )
        resumed: list[str] = []

        async def resume(
            intent: Any,
            _order: dict[str, Any],
            _config: dict[str, Any],
        ) -> bool:
            resumed.append(str(intent.operation_id))
            await service.transition(
                str(intent.operation_id),
                PlacementIntentState.PERSISTED,
            )
            return True

        summary = await PlacementReconciler(exchange, resume, service).reconcile(
            {"exchange": "binance", "market": "spot", "dry_run": False}
        )

        intent = await service.get(str(preparation.operation_id))
        assert intent.state == PlacementIntentState.COMPLETED.value
        assert intent.exchange_order_id == "exchange-sell-1"
        assert resumed == ["filled-sell"]
        assert summary.completed == 1
        assert summary.ready is True
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_unavailable_lookup_quarantines_and_blocks_readiness(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        preparation = await _prepare_live_intent(service, "unknown-sell")
        assert await service.claim_submission(preparation.operation_id) is True
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.UNAVAILABLE,
                error_message="exchange timed out",
            )
        )

        summary = await PlacementReconciler(
            exchange,
            _reject_resume,
            service,
        ).reconcile({"exchange": "binance", "market": "spot", "dry_run": False})

        intent = await service.get(str(preparation.operation_id))
        assert intent.state == PlacementIntentState.QUARANTINED.value
        assert intent.reason_code == "exchange_lookup_unavailable"
        assert summary.ready is False
        assert summary.action_required == ("unknown-sell",)
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_existing_restored_quarantine_keeps_startup_blocked(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        preparation = await _prepare_live_intent(service, "restored-sell")
        await model.PlacementIntent.filter(
            operation_id=preparation.operation_id
        ).update(state=PlacementIntentState.RESTORED_QUARANTINED.value)
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.NOT_FOUND)
        )

        summary = await PlacementReconciler(
            exchange,
            _reject_resume,
            service,
        ).reconcile({"exchange": "binance", "market": "spot", "dry_run": False})

        assert summary.inspected == 0
        assert summary.ready is False
        assert summary.action_required == ("restored-sell",)
        assert exchange.calls == []
    finally:
        await Tortoise.close_connections()
