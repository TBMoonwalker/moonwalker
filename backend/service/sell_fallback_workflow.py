"""Durable limit-to-market sell fallback orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from service.exchange_capabilities import (
    ExchangePostSubmissionFailure,
    ExchangeSubmissionIndeterminate,
)
from service.placement_intents import (
    PlacementAction,
    PlacementIntentState,
    build_derived_operation_id,
)
from service.placement_workflow import PlacementWorkflow

PersistLimitFallback = Callable[
    [dict[str, Any], dict[str, Any], str],
    Awaitable[bool],
]


@dataclass(frozen=True)
class DurableSellFallback:
    """Resolve one limit leg before claiming a distinct market child."""

    exchange: Any
    workflow: PlacementWorkflow
    persist_limit_fallback: PersistLimitFallback
    logger: Any

    async def execute(
        self,
        remaining_order: dict[str, Any],
        config: dict[str, Any],
        limit_status: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Execute a market fallback with its own durable client identity."""
        parent_operation_id = str(remaining_order.get("operation_id") or "").strip()
        partial_amount = float(limit_status.get("partial_filled_amount") or 0.0)
        if partial_amount > 0:
            await self.workflow.intents.transition(
                parent_operation_id,
                PlacementIntentState.FILLED,
                exchange_order_id=str(limit_status.get("exchange_order_id") or "")
                or None,
                result=limit_status,
            )
        else:
            await self.workflow.intents.transition(
                parent_operation_id,
                PlacementIntentState.REJECTED,
                result=limit_status,
                reason_code=str(
                    limit_status.get("fallback_reason") or "limit_resolved_without_fill"
                ),
            )

        child_order = self._build_child_order(
            remaining_order,
            parent_operation_id,
        )
        child = await self.workflow.begin(
            child_order,
            config,
            action=PlacementAction.SELL,
            side="sell",
            order_type="market",
            requested_amount=float(child_order["requested_total_amount"]),
        )
        if not child.claimed:
            self.logger.warning(
                "Skipping duplicate market fallback for %s: operation=%s state=%s.",
                child_order.get("symbol"),
                child.operation_id,
                child.state,
            )
            return None

        try:
            market_status = await self.exchange.create_spot_market_sell(
                child_order,
                config,
            )
        except ExchangeSubmissionIndeterminate as exc:
            await self.workflow.intents.transition(
                child.operation_id,
                PlacementIntentState.INDETERMINATE,
                reason_code="exchange_response_lost",
                error_message=str(exc),
            )
            exc.operation_id = child.operation_id
            raise
        except ExchangePostSubmissionFailure as exc:
            await self.workflow.intents.transition(
                child.operation_id,
                PlacementIntentState.ACCEPTED,
                exchange_order_id=str(exc.order.get("id") or "") or None,
                result=exc.order,
                reason_code="local_finalization_pending",
                error_message=str(exc.cause or exc),
            )
            exc.operation_id = child.operation_id
            raise

        if not market_status:
            await self.workflow.intents.transition(
                child.operation_id,
                PlacementIntentState.REJECTED,
                reason_code="market_fallback_rejected_or_unfilled",
            )
            if partial_amount > 0:
                await self.persist_limit_fallback(
                    limit_status,
                    config,
                    parent_operation_id,
                )
                await self.workflow.intents.transition(
                    parent_operation_id,
                    PlacementIntentState.COMPLETED,
                )
            return None

        market_status["_placement_operation_id"] = str(child.operation_id or "")
        if partial_amount > 0:
            market_status["_placement_source_operation_id"] = parent_operation_id
        return market_status

    @staticmethod
    def _build_child_order(
        remaining_order: dict[str, Any],
        parent_operation_id: str,
    ) -> dict[str, Any]:
        """Build the deterministic market child request."""
        child_order = dict(remaining_order)
        child_order["source_operation_id"] = parent_operation_id
        child_order["operation_id"] = build_derived_operation_id(
            PlacementAction.SELL,
            parent_operation_id,
            "market-fallback",
        )
        child_order.pop("client_order_id", None)
        child_order["ordertype"] = "market"
        child_order["requested_total_amount"] = float(
            child_order.get("total_amount") or 0.0
        )
        return child_order
