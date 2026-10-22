"""Startup reconciliation for durable exchange placement intents."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import ccxt.async_support as ccxt
import helper
from service.exchange_capabilities import (
    ExchangeOrderLookupStatus,
    require_exchange_placement_capabilities,
)
from service.lifecycle_routing import LifecycleRoute, load_lifecycle_route
from service.placement_intents import (
    PlacementAction,
    PlacementIntentService,
    PlacementIntentState,
    is_live_placement_enabled,
)

logging = helper.LoggerFactory.get_logger(
    "logs/placement_reconciliation.log",
    "placement_reconciliation",
)
ResumePlacement = Callable[[Any, dict[str, Any], dict[str, Any]], Awaitable[bool]]
RecoverAccumulation = Callable[[Any, dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class PlacementReconciliationSummary:
    """Readiness result for all durable operations found during startup."""

    inspected: int
    completed: int
    rejected: int
    quarantined: int
    ready: bool
    action_required: tuple[str, ...]


class PlacementReconciler:
    """Resolve unknown acceptance before any trade producer can start."""

    def __init__(
        self,
        exchange: Any,
        resume_placement: ResumePlacement,
        intents: PlacementIntentService | None = None,
        accumulation_recovery: RecoverAccumulation | None = None,
    ) -> None:
        self.exchange = exchange
        self.resume_placement = resume_placement
        self.intents = intents or PlacementIntentService()
        self.accumulation_recovery = accumulation_recovery

    async def reconcile(
        self,
        config: dict[str, Any],
    ) -> PlacementReconciliationSummary:
        """Reconcile all nonterminal operations and report startup readiness."""
        pending = await self.intents.list_nonterminal()
        completed = 0
        rejected = 0

        for intent in pending:
            outcome = await self._reconcile_one(intent, config)
            if outcome == PlacementIntentState.COMPLETED.value:
                completed += 1
            elif outcome == PlacementIntentState.REJECTED.value:
                rejected += 1

        action_required_rows = await self.intents.list_action_required()
        action_required = tuple(
            str(intent.operation_id) for intent in action_required_rows
        )
        remaining = await self.intents.list_nonterminal()
        return PlacementReconciliationSummary(
            inspected=len(pending),
            completed=completed,
            rejected=rejected,
            quarantined=len(action_required_rows),
            ready=not action_required and not remaining,
            action_required=action_required,
        )

    async def reconcile_operation(
        self, operation_id: str, config: dict[str, Any]
    ) -> str:
        """Recover an accepted operation during runtime without resubmitting it."""
        intent = await self.intents.get(operation_id)
        if intent is None:
            return PlacementIntentState.QUARANTINED.value
        if str(intent.state) not in {
            PlacementIntentState.ACCEPTED.value,
            PlacementIntentState.RECONCILING.value,
            PlacementIntentState.FILLED.value,
            PlacementIntentState.PERSISTED.value,
        }:
            return str(intent.state)
        return await self._reconcile_one(intent, config, runtime=True)

    async def _reconcile_one(
        self,
        intent: Any,
        config: dict[str, Any],
        *,
        runtime: bool = False,
    ) -> str:
        """Resolve one operation without ever resubmitting it."""
        operation_id = str(intent.operation_id)
        state = str(intent.state)
        route = await load_lifecycle_route(str(intent.symbol))
        if route.route != LifecycleRoute.CLASSIC_DCA:
            if (
                route.route == LifecycleRoute.ACCUMULATION
                and self.accumulation_recovery is not None
            ):
                try:
                    return await self.accumulation_recovery(intent, config)
                except (ValueError, OSError, ccxt.BaseError) as exc:
                    logging.error(
                        "Accumulation recovery failed for %s",
                        operation_id,
                        exc_info=True,
                    )
                    reason = str(exc)
            else:
                reason = "Accumulation account validation and recovery must be connected before execution."
            await self._quarantine(
                operation_id,
                reason_code="accumulation_recovery_required",
                error_message=reason,
            )
            return PlacementIntentState.QUARANTINED.value
        if state == PlacementIntentState.PREPARED.value:
            await self.intents.transition(
                operation_id,
                PlacementIntentState.REJECTED,
                reason_code="startup_confirmed_never_submitted",
            )
            return PlacementIntentState.REJECTED.value
        if state == PlacementIntentState.PERSISTED.value:
            await self.intents.transition(
                operation_id,
                PlacementIntentState.COMPLETED,
            )
            return PlacementIntentState.COMPLETED.value
        if state == PlacementIntentState.FILLED.value:
            return await self._resume_or_quarantine(intent, {}, config)

        if (
            not is_live_placement_enabled(config)
            or str(config.get("exchange") or "").strip().lower()
            != str(intent.exchange_name).strip().lower()
        ):
            await self._quarantine(
                operation_id,
                reason_code="reconciliation_exchange_unavailable",
                error_message=(
                    "The active live exchange does not match the pending placement."
                ),
            )
            return PlacementIntentState.QUARANTINED.value

        try:
            require_exchange_placement_capabilities(
                config,
                order_type=str(intent.order_type),
            )
        except ValueError as exc:
            await self._quarantine(
                operation_id,
                reason_code="reconciliation_capability_unavailable",
                error_message=str(exc),
            )
            return PlacementIntentState.QUARANTINED.value

        if state == PlacementIntentState.SUBMITTING.value:
            await self.intents.transition(
                operation_id,
                PlacementIntentState.INDETERMINATE,
                reason_code="startup_found_submitting",
            )
        try:
            await self.intents.mark_reconciling(operation_id)
            lookup = await self.exchange.lookup_spot_order(
                str(intent.symbol),
                config,
                exchange_order_id=(
                    str(intent.exchange_order_id)
                    if intent.exchange_order_id is not None
                    else None
                ),
                client_order_id=(
                    str(intent.client_order_id)
                    if intent.client_order_id is not None
                    else None
                ),
            )
        except asyncio.CancelledError:
            if runtime:
                await asyncio.shield(
                    self.intents.transition(
                        operation_id,
                        PlacementIntentState.ACCEPTED,
                        reason_code="runtime_lookup_canceled",
                    )
                )
            raise
        except (ccxt.BaseError, OSError, TimeoutError) as exc:
            if not runtime:
                raise
            logging.warning(
                "Accepted buy lookup remains pending for %s: %s", operation_id, exc
            )
            await self.intents.transition(
                operation_id,
                PlacementIntentState.ACCEPTED,
                reason_code="runtime_lookup_pending",
            )
            return PlacementIntentState.ACCEPTED.value
        if runtime and (
            lookup.status != ExchangeOrderLookupStatus.FOUND or lookup.order is None
        ):
            await self.intents.transition(
                operation_id,
                PlacementIntentState.ACCEPTED,
                reason_code="runtime_lookup_pending",
            )
            return PlacementIntentState.ACCEPTED.value
        if lookup.status == ExchangeOrderLookupStatus.NOT_FOUND:
            await self.intents.transition(
                operation_id,
                PlacementIntentState.REJECTED,
                reason_code="exchange_identity_not_found",
                error_message=lookup.error_message,
            )
            return PlacementIntentState.REJECTED.value
        if lookup.status != ExchangeOrderLookupStatus.FOUND or lookup.order is None:
            await self._quarantine(
                operation_id,
                reason_code="exchange_lookup_unavailable",
                error_message=lookup.error_message,
            )
            return PlacementIntentState.QUARANTINED.value

        order = lookup.order
        exchange_state = str(order.get("status") or "").strip().lower()
        action = str(intent.action)
        terminal_states = {
            "closed",
            "filled",
            "canceled",
            "cancelled",
            "rejected",
            "expired",
        }
        if action == PlacementAction.BUY.value:
            try:
                raw_filled = order.get("filled")
                if raw_filled is None or isinstance(raw_filled, bool):
                    raise ValueError("Missing buy fill evidence")
                buy_filled = float(raw_filled)
                if not math.isfinite(buy_filled) or buy_filled < 0:
                    raise ValueError("Invalid buy fill evidence")
            except (TypeError, ValueError):
                buy_filled = None
            if (
                buy_filled is not None
                and buy_filled > 0
                and exchange_state in terminal_states
            ):
                await self.intents.transition(
                    operation_id,
                    PlacementIntentState.FILLED,
                    exchange_order_id=str(order.get("id") or "") or None,
                    result=order,
                )
                return await self._resume_or_quarantine(intent, order, config)
            if (
                buy_filled is None
                or exchange_state not in terminal_states
                or (buy_filled == 0 and exchange_state in {"closed", "filled"})
            ):
                if runtime:
                    await self.intents.transition(
                        operation_id,
                        PlacementIntentState.ACCEPTED,
                        reason_code="runtime_fill_pending",
                    )
                    return PlacementIntentState.ACCEPTED.value
                await self._quarantine(
                    operation_id,
                    reason_code="buy_fill_unconfirmed",
                    error_message="Buy order has no definitive terminal fill evidence.",
                )
                return PlacementIntentState.QUARANTINED.value
        if exchange_state in {"canceled", "cancelled", "rejected", "expired"}:
            if action == PlacementAction.CANCEL.value:
                await self.intents.transition(
                    operation_id,
                    PlacementIntentState.ACCEPTED,
                    exchange_order_id=str(order.get("id") or "") or None,
                    result=order,
                )
                return await self._resume_or_quarantine(intent, order, config)
            await self.intents.transition(
                operation_id,
                PlacementIntentState.REJECTED,
                exchange_order_id=str(order.get("id") or "") or None,
                result=order,
                reason_code=f"exchange_order_{exchange_state}",
            )
            return PlacementIntentState.REJECTED.value

        filled = float(order.get("filled") or 0.0)
        amount = float(order.get("amount") or 0.0)
        is_filled = exchange_state in {"closed", "filled"} or (
            amount > 0 and filled >= amount
        )
        if is_filled:
            await self.intents.transition(
                operation_id,
                PlacementIntentState.FILLED,
                exchange_order_id=str(order.get("id") or "") or None,
                result=order,
            )
            return await self._resume_or_quarantine(intent, order, config)

        if action == PlacementAction.LIMIT_SELL.value and exchange_state == "open":
            await self.intents.transition(
                operation_id,
                PlacementIntentState.ACCEPTED,
                exchange_order_id=str(order.get("id") or "") or None,
                result=order,
            )
            return await self._resume_or_quarantine(intent, order, config)

        await self._quarantine(
            operation_id,
            reason_code="unsupported_reconciliation_state",
            error_message=f"Exchange returned order state '{exchange_state or 'unknown'}'.",
        )
        return PlacementIntentState.QUARANTINED.value

    async def _resume_or_quarantine(
        self,
        intent: Any,
        exchange_order: dict[str, Any],
        config: dict[str, Any],
    ) -> str:
        """Resume local persistence, quarantining any unsafe or failed branch."""
        try:
            persisted = await self.resume_placement(intent, exchange_order, config)
        except Exception as exc:  # noqa: BLE001 - startup must fail closed.
            logging.error(
                "Placement recovery failed for %s: %s",
                intent.operation_id,
                exc,
                exc_info=True,
            )
            persisted = False
            error_message = str(exc)
        else:
            error_message = "Local persistence could not be resumed safely."
        if not persisted:
            await self._quarantine(
                str(intent.operation_id),
                reason_code="local_recovery_failed",
                error_message=error_message,
            )
            return PlacementIntentState.QUARANTINED.value
        await self.intents.transition(
            str(intent.operation_id),
            PlacementIntentState.COMPLETED,
        )
        return PlacementIntentState.COMPLETED.value

    async def _quarantine(
        self,
        operation_id: str,
        *,
        reason_code: str,
        error_message: str | None,
    ) -> None:
        """Move any recoverable nonterminal state to operator action required."""
        await self.intents.transition(
            operation_id,
            PlacementIntentState.QUARANTINED,
            reason_code=reason_code,
            error_message=error_message,
        )
