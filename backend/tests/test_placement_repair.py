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

import json
from datetime import datetime, timezone
from typing import Any

import model
import pytest
from service.exchange_capabilities import (
    ExchangeOrderLookupResult,
    ExchangeOrderLookupStatus,
)
from service.lifecycle_routing import LifecycleRoute, LifecycleRoutingDecision
from service.placement_intents import (
    PlacementIntentService,
    PlacementIntentState,
)
from service.placement_repair import (
    PlacementRepairConflict,
    PlacementRepairInvalid,
    PlacementRepairNotFound,
    PlacementRepairService,
)
from tortoise import Tortoise


async def _init_database(tmp_path) -> None:
    database_path = tmp_path / "placement-repair.sqlite"
    await Tortoise.init(
        db_url=f"sqlite://{database_path}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()


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
    ) -> bool:
        self.calls.append((str(intent.operation_id), dict(exchange_order)))
        if self.error is not None:
            raise self.error
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
) -> Any:
    return await model.PlacementIntent.create(
        operation_id=operation_id,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        exchange_name="binance",
        symbol="BTC/USDC",
        action="limit_sell",
        side="sell",
        order_type="limit",
        state=state,
        requested_quote=120.0,
        requested_amount=0.6,
        maximum_price=0.2,
        request_json=json.dumps({"limit_price": 0.2, "total_amount": 0.6}),
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
async def test_repair_unknown_operation_raises_not_found(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        service = _service(
            _FakeExchange(
                ExchangeOrderLookupResult(status=ExchangeOrderLookupStatus.UNAVAILABLE)
            )
        )

        with pytest.raises(PlacementRepairNotFound):
            await service.repair("limit_sell-missing", {"exchange": "binance"})
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_repair_non_quarantined_raises_conflict(tmp_path) -> None:
    await _init_database(tmp_path)
    try:
        intents = PlacementIntentService()
        preparation = await intents.prepare(
            {"operation_id": "live-buy", "symbol": "BTC/USDC"},
            {"exchange": "binance"},
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
            await service.repair(str(preparation.operation_id), {"exchange": "binance"})
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
            await service.repair("limit_sell-test", {"exchange": "binance"})
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

        result = await _service(exchange).repair(
            "limit_sell-test", {"exchange": "binance"}
        )

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
        ).repair("limit_sell-test", {"exchange": "binance"})

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

        result = await _service(exchange).repair(
            "limit_sell-test", {"exchange": "binance"}
        )

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
            "limit_sell-test", {"exchange": "binance"}
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
            "limit_sell-test", {"exchange": "binance"}
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
            "limit_sell-test", {"exchange": "binance"}
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
            "limit_sell-test", {"exchange": "binance"}
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
        ).repair("limit_sell-test", {"exchange": "binance"})

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
            request_json="{}",
            reason_code="buy_fill_unconfirmed",
            completed_at=datetime.now(timezone.utc),
        )

        result = await _service(exchange, resume=resume).repair(
            "buy-test", {"exchange": "binance"}
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
            request_json="{}",
            reason_code="local_recovery_failed",
            completed_at=datetime.now(timezone.utc),
        )

        result = await _service(exchange, resume=resume).repair(
            "sell-test", {"exchange": "binance"}
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
            request_json="{}",
            reason_code="local_recovery_failed",
            completed_at=datetime.now(timezone.utc),
        )

        result = await _service(exchange, resume=resume).repair(
            "cancel-test", {"exchange": "binance"}
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

        result = await _service(exchange).repair(
            "limit_sell-test", {"exchange": "binance"}
        )
        assert result["status"] == "completed"
        with pytest.raises(PlacementRepairConflict):
            await _service(exchange).repair("limit_sell-test", {"exchange": "binance"})

        assert [call["symbol"] for call in exchange.calls] == ["BTC/USDC"]
        assert not hasattr(exchange, "create_order")
    finally:
        await Tortoise.close_connections()
