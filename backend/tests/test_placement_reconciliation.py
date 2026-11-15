"""Regression coverage for fail-closed placement reconciliation."""

from __future__ import annotations

import json
from collections.abc import Awaitable
from typing import Any

import model
import pytest
from service.exchange_capabilities import (
    ExchangeOrderLookupResult,
    ExchangeOrderLookupStatus,
)
from service.exchange_order_lookup import build_parsed_order_status
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
async def test_canceled_partial_sell_stays_quarantined(tmp_path) -> None:
    """An exchange partial fill cannot be discarded as a rejected sell."""
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        preparation = await _prepare_live_intent(service, "partial-sell")
        assert await service.claim_submission(preparation.operation_id) is True
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={"id": "42", "status": "canceled", "filled": 0.2},
            )
        )
        summary = await PlacementReconciler(
            exchange, _reject_resume, service
        ).reconcile({"exchange": "binance", "market": "spot", "dry_run": False})
        intent = await service.get(str(preparation.operation_id))
        assert intent.state == PlacementIntentState.QUARANTINED.value
        assert summary.ready is False
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence",
    [
        {},
        {"filled": True},
        {"filled": -1},
        {"filled": "nan"},
        {"filled": 0.4, "amount": 0.5, "cost": 4},
        {"filled": 0.4},
        {"filled": 0.4, "cost": "inf"},
        {"filled": 0.4, "cost": 4, "average": "inf"},
        {"filled": 1e-308, "cost": 1e308},
    ],
)
async def test_startup_cancel_unreliable_evidence_never_resumes(tmp_path, evidence):
    """Startup must not clear a TP or persist a fill from inconclusive evidence."""
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        config = {"exchange": "binance", "market": "spot", "dry_run": False}
        prepared = await service.prepare(
            {"operation_id": "cancel-unsafe", "symbol": "BTC/USDC"},
            config,
            action=PlacementAction.CANCEL,
            side="sell",
            order_type="limit",
            requested_amount=1.0,
            exchange_order_id="tp1",
        )
        assert await service.claim_submission(prepared.operation_id)
        calls = []

        async def resume(intent, order, config):
            calls.append(order)
            await service.transition(
                intent.operation_id, PlacementIntentState.PERSISTED
            )
            return True

        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={"id": "tp1", "status": "canceled", **evidence},
            )
        )
        summary = await PlacementReconciler(exchange, resume, service).reconcile(config)
        intent = await service.get(prepared.operation_id)
        assert intent.state == PlacementIntentState.QUARANTINED.value
        assert not summary.ready
        assert calls == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", [PlacementAction.SELL, PlacementAction.LIMIT_SELL, PlacementAction.CANCEL]
)
@pytest.mark.parametrize(
    "evidence",
    [
        {},
        {"filled": 0.5, "amount": 1.0},
        {"filled": 1.0, "amount": 2.0},
        {"filled": "bad", "amount": 1.0},
        {"filled": "nan", "amount": 1.0},
        {"filled": 1.0, "amount": "bad"},
        {"filled": 1.0, "amount": True},
    ],
)
async def test_startup_closed_sell_requires_complete_fill(tmp_path, action, evidence):
    """A terminal status alone does not prove the intended sell completed."""
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        config = {"exchange": "binance", "market": "spot", "dry_run": False}
        prepared = await service.prepare(
            {"operation_id": "incomplete-sell", "symbol": "BTC/USDC"},
            config,
            action=action,
            side="sell",
            order_type="limit",
            requested_amount=1.0,
            exchange_order_id="tp1",
        )
        assert await service.claim_submission(prepared.operation_id)
        calls = []

        async def resume(intent, order, config):
            calls.append(order)
            await service.transition(
                intent.operation_id, PlacementIntentState.PERSISTED
            )
            return True

        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={"id": "tp1", "status": "closed", **evidence},
            )
        )
        summary = await PlacementReconciler(exchange, resume, service).reconcile(config)
        assert (
            await service.get(prepared.operation_id)
        ).state == PlacementIntentState.QUARANTINED.value
        assert not summary.ready
        assert calls == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence", [{"filled": 0}, {"filled": 0.4, "amount": 1, "cost": 4}]
)
async def test_startup_cancel_with_reliable_evidence_resumes(tmp_path, evidence):
    """A confirmed zero or partial cancellation still reaches persistence."""
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        config = {"exchange": "binance", "market": "spot", "dry_run": False}
        prepared = await service.prepare(
            {"operation_id": "valid-cancel", "symbol": "BTC/USDC"},
            config,
            action=PlacementAction.CANCEL,
            side="sell",
            order_type="limit",
            requested_amount=1,
            exchange_order_id="tp1",
        )
        assert await service.claim_submission(prepared.operation_id)
        calls = []

        async def resume(intent, order, config):
            calls.append(order)
            await service.transition(
                intent.operation_id, PlacementIntentState.PERSISTED
            )
            return True

        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={"id": "tp1", "status": "canceled", **evidence},
            )
        )
        summary = await PlacementReconciler(exchange, resume, service).reconcile(config)
        assert summary.ready
        assert len(calls) == 1
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence,expected_ready",
    [({}, False), ({"filled": 0.5}, False), ({"filled": 1.0, "amount": 1.0}, True)],
)
async def test_startup_stored_filled_sell_requires_complete_evidence(
    tmp_path, evidence, expected_ready
):
    """A previously FILLED intent must still prove the whole durable quantity."""
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        config = {"exchange": "binance", "market": "spot", "dry_run": False}
        prepared = await service.prepare(
            {"operation_id": "stored-fill", "symbol": "BTC/USDC"},
            config,
            action=PlacementAction.SELL,
            side="sell",
            order_type="market",
            requested_amount=1,
        )
        assert await service.claim_submission(prepared.operation_id)
        await service.transition(
            prepared.operation_id, PlacementIntentState.FILLED, result=evidence
        )
        calls = []

        async def resume(intent, order, config):
            calls.append(order)
            await service.transition(
                intent.operation_id, PlacementIntentState.PERSISTED
            )
            return True

        exchange = _FakeExchange(
            ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
        )
        summary = await PlacementReconciler(exchange, resume, service).reconcile(config)
        assert summary.ready is expected_ready
        assert len(calls) == int(expected_ready)
        assert exchange.calls == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", [None, "identity", "quantity", "proceeds"])
async def test_startup_replays_normalized_sell_only_with_matching_report(
    tmp_path, corrupt
):
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        config = {"exchange": "binance", "market": "spot", "dry_run": False}
        prepared = await _prepare_live_intent(service, "normalized-sell")
        assert await service.claim_submission(prepared.operation_id)
        evidence = build_parsed_order_status(
            {
                "id": "sell-1",
                "symbol": "BTC/USDC",
                "side": "sell",
                "status": "closed",
                "filled": 1,
                "amount": 1,
                "cost": 120,
                "timestamp": 1,
            },
            None,
        )
        if corrupt == "identity":
            evidence["orderid"] = "other"
        elif corrupt == "quantity":
            evidence["total_amount"] = 0.5
        elif corrupt == "proceeds":
            evidence["ordersize"] = 60
        await service.transition(
            prepared.operation_id,
            PlacementIntentState.FILLED,
            exchange_order_id="sell-1",
            result=evidence,
        )
        calls = []

        async def resume(intent, order, config):
            calls.append(intent.operation_id)
            await service.transition(
                intent.operation_id, PlacementIntentState.PERSISTED
            )
            return True

        exchange = _FakeExchange(
            ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
        )
        summary = await PlacementReconciler(exchange, resume, service).reconcile(config)
        assert summary.ready is (corrupt is None)
        assert len(calls) == int(corrupt is None)
        assert exchange.calls == []
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
                    "clientOrderId": preparation.client_order_id,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["submitting", "filled", "persisted"])
@pytest.mark.parametrize(
    "change",
    [
        {"dry_run": True},
        {"key": "other-account"},
        {"exchange_hostname": "other.example"},
        {"sandbox": True},
    ],
)
async def test_scope_change_blocks_lookup_and_saved_result_replay(
    tmp_path, state, change
):
    await _init_database(tmp_path)
    try:
        service = PlacementIntentService()
        config = {
            "exchange": "binance",
            "market": "spot",
            "dry_run": False,
            "key": "test-key-original-account",
            "secret": "test-secret-scope-sentinel",
        }
        prepared = await service.prepare(
            {"operation_id": "scoped-buy", "symbol": "BTC/USDC", "amount": 1},
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type="market",
        )
        assert await service.claim_submission(prepared.operation_id)
        if state in {"filled", "persisted"}:
            await service.transition(
                prepared.operation_id,
                PlacementIntentState.FILLED,
                result={"id": "accepted-order"},
            )
        if state == "persisted":
            await service.transition(
                prepared.operation_id, PlacementIntentState.PERSISTED
            )
        original = await service.get(prepared.operation_id)
        original_json = original.request_json
        client_id = original.client_order_id
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                ExchangeOrderLookupStatus.FOUND, {"id": "accepted-order"}
            )
        )
        summary = await PlacementReconciler(
            exchange, _reject_resume, service
        ).reconcile({**config, **change})
        row = await service.get(prepared.operation_id)
        assert not summary.ready and summary.action_required == ("scoped-buy",)
        assert row.state == "quarantined"
        assert row.reason_code == "reconciliation_account_scope_unverified"
        assert row.request_json == original_json and row.client_order_id == client_id
        assert exchange.calls == []
        assert "test-secret-scope-sentinel" not in row.request_json
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action, order_type, side",
    [
        ("limit_sell", "limit", "sell"),
        ("buy", "market", "buy"),
    ],
)
async def test_legacy_unscoped_persisted_intent_completes_without_lookup(
    tmp_path,
    action: str,
    order_type: str,
    side: str,
) -> None:
    """Intents persisted before the account-scope field existed must not lock startup.

    A persisted intent already committed its local business state, so
    completing it performs no exchange I/O and needs no verified account
    binding. Quarantining it instead keeps the fail-closed startup gate
    permanently red after an in-place upgrade.
    """
    await _init_database(tmp_path)
    try:
        row = await model.PlacementIntent.create(
            operation_id=f"{action}-legacy-persisted",
            client_order_id="mw-legacy-client",
            symbol="BTC/USDC",
            exchange_name="binance",
            action=action,
            side=side,
            order_type=order_type,
            state="persisted",
            request_json='{"symbol":"BTC/USDC","total_amount":1.0}',
        )
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.NOT_FOUND,
                error_message="lookup must not run for a persisted intent",
            )
        )

        summary = await PlacementReconciler(exchange, _reject_resume).reconcile(
            {"exchange": "binance", "market": "spot", "dry_run": False}
        )

        await row.refresh_from_db()
        assert row.state == PlacementIntentState.COMPLETED.value
        assert row.reason_code is None
        assert exchange.calls == []
        assert summary.completed == 1
        assert summary.quarantined == 0
        assert summary.ready is True
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_legacy_unscoped_result_stays_unresolved_without_invented_binding(
    tmp_path,
):
    await _init_database(tmp_path)
    try:
        row = await model.PlacementIntent.create(
            operation_id="old-buy",
            client_order_id="original-client",
            symbol="BTC/USDC",
            exchange_name="binance",
            action="buy",
            side="buy",
            order_type="market",
            state="filled",
            request_json='{"symbol":"BTC/USDC"}',
            result_json='{"id":"old-accepted-order"}',
        )
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(ExchangeOrderLookupStatus.FOUND)
        )
        summary = await PlacementReconciler(exchange, _reject_resume).reconcile(
            {"exchange": "binance", "dry_run": False}
        )
        await row.refresh_from_db()
        assert not summary.ready and row.state == "quarantined"
        assert row.request_json == '{"symbol":"BTC/USDC"}'
        assert row.result_json == '{"id":"old-accepted-order"}'
        assert exchange.calls == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("known_id", "lookup_identity", "expected_state"),
    [
        ("exchange-1", {"id": "exchange-1"}, "rejected"),
        ("exchange-1", {"id": "exchange-1", "symbol": "ETH/USDC"}, "quarantined"),
        ("exchange-1", {"id": "exchange-1", "side": "buy"}, "quarantined"),
        (
            "exchange-1",
            {"id": "exchange-1", "symbol": "BTC/USDC", "side": "sell"},
            "rejected",
        ),
        ("exchange-1", {"id": "wrong"}, "quarantined"),
        (None, {"clientOrderId": "match-client"}, "rejected"),
        (None, {"info": {"orderLinkId": "match-client"}}, "rejected"),
        (None, {"clientOrderId": "wrong"}, "quarantined"),
        (None, {"id": "unbound"}, "quarantined"),
    ],
)
async def test_startup_lookup_requires_matching_durable_identity(
    tmp_path, known_id: str | None, lookup_identity: dict[str, Any], expected_state: str
) -> None:
    """A different exchange order cannot release or apply a pending placement."""
    from service.exchange_capabilities import exchange_execution_scope

    await _init_database(tmp_path)
    try:
        config = {"exchange": "binance", "market": "spot", "dry_run": False}
        await model.PlacementIntent.create(
            operation_id="identity-check",
            client_order_id="match-client",
            exchange_order_id=known_id,
            exchange_name="binance",
            symbol="BTC/USDC",
            action="sell",
            side="sell",
            order_type="market",
            state="submitting",
            requested_amount=1,
            request_json=json.dumps(
                {"_execution_scope": exchange_execution_scope(config)}
            ),
        )
        exchange = _FakeExchange(
            ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.FOUND,
                order={"status": "canceled", "filled": 0, **lookup_identity},
            )
        )
        summary = await PlacementReconciler(exchange, _reject_resume).reconcile(config)
        intent = await model.PlacementIntent.get(operation_id="identity-check")
        assert intent.state == expected_state
        assert summary.ready is (expected_state == "rejected")
        if expected_state == "quarantined":
            assert intent.reason_code == "exchange_identity_mismatch"
    finally:
        await Tortoise.close_connections()
