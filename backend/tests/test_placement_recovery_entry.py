"""Unit coverage for the placement-recovery entry composition.

Value: protects=the entry receives and keeps the caller-constructed
    DcaOrderLifecycle (no second collaborator set), wires the bybit
    reconciler factory to its own call-time seam read, closes the composed
    exchange in a finally on every reconcile path, and builds the operator
    repair service over the shared recovery resume handler.
fails_when=the entry self-constructs a replacement lifecycle, drops the
    reconciler-factory wiring, captures the accumulation seam at init
    instead of reading it at reconciler-construction time, or skips the
    finally close.
why_new=these seams moved off the Orders facade when service/orders.py was
    removed; the facade-specific composition guard is re-homed here against
    the new owner.
seam=none (unit-level; exchange and reconciler are fakes).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import service.placement_recovery_entry as entry_module
from service.dca.order_lifecycle import DcaOrderLifecycle
from service.placement_intents import PlacementAction, PlacementIntentState
from service.placement_reconciliation import (
    PlacementReconciliationSummary,
)
from service.placement_recovery_entry import PlacementRecoveryEntry


class _CaptureReconciler:
    def __init__(
        self,
        exchange: Any,
        resume: Any,
        intents: Any,
        *,
        accumulation_recovery: Any = None,
    ) -> None:
        self.captured: list[Any] = []
        self.captured.append(accumulation_recovery)
        self.resume_placement = resume

    async def reconcile_operation(self, _operation_id: str, _config: Any) -> str:
        return PlacementIntentState.REJECTED.value

    async def reconcile(self, _config: Any) -> PlacementReconciliationSummary:
        return PlacementReconciliationSummary(
            inspected=0,
            completed=0,
            rejected=0,
            quarantined=0,
            ready=True,
            action_required=(),
        )


def test_entry_keeps_passed_lifecycle_and_wires_factory() -> None:
    """The entry composes the given lifecycle and points its bybit factory at itself."""
    lifecycle = DcaOrderLifecycle()
    entry = PlacementRecoveryEntry(lifecycle=lifecycle)

    assert entry.dca is lifecycle
    assert lifecycle.reconciler_factory is not None
    assert lifecycle.reconciler_factory.__self__ is entry
    assert (
        lifecycle.reconciler_factory.__func__
        is entry_module.PlacementRecoveryEntry.build_reconciler
    )
    assert entry.accumulation_recovery is None


@pytest.mark.asyncio
async def test_entry_close_delegates_to_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing the entry closes the composed lifecycle's exchange exactly once."""
    lifecycle = DcaOrderLifecycle()
    entry = PlacementRecoveryEntry(lifecycle=lifecycle)
    closed: list[bool] = []

    async def fake_close() -> None:
        closed.append(True)

    monkeypatch.setattr(lifecycle.exchange, "close", fake_close)

    await entry.close()

    assert closed == [True]


@pytest.mark.asyncio
async def test_reconcile_placement_intents_closes_exchange_in_finally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The startup entry closes the exchange on both the success and raised paths."""
    lifecycle = DcaOrderLifecycle()
    entry = PlacementRecoveryEntry(lifecycle=lifecycle)
    closed: list[bool] = []

    async def fake_close() -> None:
        closed.append(True)

    monkeypatch.setattr(lifecycle.exchange, "close", fake_close)
    monkeypatch.setattr(entry_module, "PlacementReconciler", _CaptureReconciler)

    result = await entry.reconcile_placement_intents({})
    assert result.ready is True
    assert closed == [True]

    class _FailingReconciler(_CaptureReconciler):
        async def reconcile(self, _config: Any) -> PlacementReconciliationSummary:
            raise RuntimeError("reconcile failed")

    monkeypatch.setattr(entry_module, "PlacementReconciler", _FailingReconciler)
    with pytest.raises(RuntimeError, match="reconcile failed"):
        await entry.reconcile_placement_intents({})

    assert closed == [True, True]


@pytest.mark.asyncio
async def test_bybit_reconciler_reads_seam_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seam assigned after construction is observed by the bybit branch.

    Mirrors the D6 late-binding guard: the reconciler factory must read
    ``accumulation_recovery`` at reconciler-construction time, not capture it
    at entry construction, or repair-only accumulation intents would silently
    route to the classic path.
    """
    lifecycle = DcaOrderLifecycle()
    entry = PlacementRecoveryEntry(lifecycle=lifecycle)
    sentinel = object()

    monkeypatch.setattr(entry_module, "PlacementReconciler", _CaptureReconciler)
    pending = SimpleNamespace(
        operation_id="buy-late-seam",
        exchange_name="bybit",
        symbol="DOGE/USDC",
        action=PlacementAction.BUY.value,
        state=PlacementIntentState.ACCEPTED.value,
    )

    async def fake_list_nonterminal() -> list[Any]:
        return [pending]

    monkeypatch.setattr(
        lifecycle.placement_intents, "list_nonterminal", fake_list_nonterminal
    )

    # Pre-assignment build: the seam is still unbound.
    pre = entry.build_reconciler()
    assert pre.captured == [None]

    entry.accumulation_recovery = sentinel
    filled, precheck = await lifecycle._execute_budgeted_buy_order(
        {"symbol": "DOGE/USDC", "ordersize": 5},
        {"exchange": "bybit", "dry_run": True},
    )

    assert filled is False
    assert precheck is not None
    assert precheck["reason"] == "placement_rejected"


def test_build_placement_repair_wires_shared_recovery_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The repair service reuses the entry's reconciler resume and collaborators."""
    lifecycle = DcaOrderLifecycle()
    entry = PlacementRecoveryEntry(lifecycle=lifecycle)
    captured: dict[str, Any] = {}

    class _RecordingReconciler(_CaptureReconciler):
        def __init__(
            self,
            exchange: Any,
            resume: Any,
            intents: Any,
            *,
            accumulation_recovery: Any = None,
        ) -> None:
            super().__init__(
                exchange, resume, intents, accumulation_recovery=accumulation_recovery
            )
            captured["resume"] = resume
            captured["exchange"] = exchange
            captured["intents"] = intents

    class _RecordingRepairService:
        def __init__(
            self,
            exchange: Any,
            intents: Any,
            resume_placement: Any,
        ) -> None:
            captured["repair_exchange"] = exchange
            captured["repair_intents"] = intents
            captured["repair_resume"] = resume_placement

    monkeypatch.setattr(entry_module, "PlacementReconciler", _RecordingReconciler)
    monkeypatch.setattr(entry_module, "PlacementRepairService", _RecordingRepairService)

    entry.build_placement_repair()

    assert captured["repair_exchange"] is lifecycle.exchange
    assert captured["repair_intents"] is lifecycle.placement_intents
    assert captured["repair_resume"] is captured["resume"]
