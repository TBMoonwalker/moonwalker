"""Regression coverage for ambiguous terminal order evidence."""

from types import SimpleNamespace

import pytest
from service.placement_repair import PlacementRepairService


class _IntentStore:
    async def release_quarantine(self, operation_id, state, **kwargs):
        return SimpleNamespace(operation_id=operation_id, state=state)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "order"),
    [
        ("buy", {"status": "canceled"}),
        ("limit_sell", {"status": "canceled", "filled": 0.2, "amount": 0.6}),
        ("sell", {"status": "expired"}),
        ("limit_sell", {"status": "closed", "filled": 0.2, "amount": 0.6}),
        ("sell", {"status": "closed", "amount": 0.6}),
        ("sell", {"status": "closed", "filled": 0, "amount": 0.6}),
    ],
)
async def test_ambiguous_terminal_order_remains_quarantined(action, order):
    """Unknown buy fills and unapplied sell fills cannot release the gate."""
    service = PlacementRepairService(None, _IntentStore(), None)
    intent = SimpleNamespace(
        operation_id="test", action=action, state="quarantined", requested_amount=0.6
    )
    result = await service._apply_found_evidence(intent, order, {})
    assert result["status"] == "unchanged"
    assert result["state"] == "quarantined"
