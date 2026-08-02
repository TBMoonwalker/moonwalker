"""Shared orchestration for claiming and advancing durable exchange effects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from service.placement_intents import (
    PlacementAction,
    PlacementIntentService,
    PlacementIntentState,
)


class PlacementStartStatus(StrEnum):
    """Outcome of attempting to own one durable placement operation."""

    CLAIMED = "claimed"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PlacementStart:
    """Stable identity and ownership result returned to order orchestration."""

    status: PlacementStartStatus
    operation_id: str | None
    client_order_id: str | None
    state: str | None

    @property
    def claimed(self) -> bool:
        """Return whether this caller exclusively owns exchange submission."""
        return self.status == PlacementStartStatus.CLAIMED

    @property
    def completed(self) -> bool:
        """Return whether the operation was already persisted successfully."""
        return self.status == PlacementStartStatus.COMPLETED


class PlacementWorkflow:
    """Centralize prepare, deduplication, and single-submitter ownership."""

    def __init__(self, intents: PlacementIntentService | None = None) -> None:
        self.intents = intents or PlacementIntentService()

    async def begin(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
        *,
        action: PlacementAction | str,
        side: str,
        order_type: str,
        requested_quote: float = 0.0,
        requested_amount: float = 0.0,
        reserved_quote: float = 0.0,
        exchange_order_id: str | None = None,
    ) -> PlacementStart:
        """Prepare and atomically claim one operation, or deduplicate it."""
        preparation = await self.intents.prepare(
            order,
            config,
            action=action,
            side=side,
            order_type=order_type,
            requested_quote=requested_quote,
            requested_amount=requested_amount,
            reserved_quote=reserved_quote,
            exchange_order_id=exchange_order_id,
        )
        if preparation.operation_id is None:
            return PlacementStart(
                status=PlacementStartStatus.CLAIMED,
                operation_id=None,
                client_order_id=None,
                state=None,
            )

        state = str(preparation.intent.state)
        if preparation.blocked_by_conflict:
            return PlacementStart(
                status=PlacementStartStatus.BLOCKED,
                operation_id=preparation.operation_id,
                client_order_id=preparation.client_order_id,
                state=state,
            )
        if state == PlacementIntentState.PERSISTED.value:
            await self.intents.transition(
                preparation.operation_id,
                PlacementIntentState.COMPLETED,
            )
            return PlacementStart(
                status=PlacementStartStatus.COMPLETED,
                operation_id=preparation.operation_id,
                client_order_id=preparation.client_order_id,
                state=PlacementIntentState.COMPLETED.value,
            )
        if state == PlacementIntentState.COMPLETED.value:
            return PlacementStart(
                status=PlacementStartStatus.COMPLETED,
                operation_id=preparation.operation_id,
                client_order_id=preparation.client_order_id,
                state=state,
            )
        if (
            state != PlacementIntentState.PREPARED.value
            or not await self.intents.claim_submission(preparation.operation_id)
        ):
            latest = await self.intents.get(preparation.operation_id)
            return PlacementStart(
                status=PlacementStartStatus.BLOCKED,
                operation_id=preparation.operation_id,
                client_order_id=preparation.client_order_id,
                state=str(latest.state) if latest is not None else state,
            )
        return PlacementStart(
            status=PlacementStartStatus.CLAIMED,
            operation_id=preparation.operation_id,
            client_order_id=preparation.client_order_id,
            state=PlacementIntentState.SUBMITTING.value,
        )
