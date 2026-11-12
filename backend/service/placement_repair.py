"""Explicit operator repair for quarantined classic-DCA placement intents.

A quarantined row keeps the fail-closed startup gate red until an operator
resolves it. This service is the mode-neutral exit for classic-DCA intents:
it looks the order up under the currently configured credentials and applies
terminal evidence through the same resume handler the startup reconciliation
uses, or records an explicit operator dismissal. Every path is lookup-only:
nothing here submits, cancels, or otherwise changes exchange state.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import ccxt.async_support as ccxt
import helper
from service.exchange_capabilities import (
    ExchangeOrderLookupResult,
    ExchangeOrderLookupStatus,
)
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.lifecycle_routing import LifecycleRoute, load_lifecycle_route
from service.placement_intents import (
    PlacementAction,
    PlacementIntentService,
    PlacementIntentState,
    deserialize_placement_payload,
    has_execution_scope,
    is_exchange_placement_enabled,
    placement_scope_matches,
)

logging = helper.LoggerFactory.get_logger(
    "logs/placement_repair.log",
    "placement_repair",
)

LOOKUP_TIMEOUT_SECONDS = 10
MAX_DISMISS_NOTE_LENGTH = 2000

QUARANTINED_STATES = frozenset(
    {
        PlacementIntentState.QUARANTINED.value,
        PlacementIntentState.RESTORED_QUARANTINED.value,
    }
)

TERMINAL_EXCHANGE_STATES = frozenset(
    {
        "closed",
        "filled",
        "canceled",
        "cancelled",
        "rejected",
        "expired",
    }
)

TERMINAL_REPAIR_STATUSES = frozenset({"completed", "rejected", "dismissed"})


class PlacementRepairError(ValueError):
    """Base error for operator placement-repair requests."""


class PlacementRepairNotFound(PlacementRepairError):
    """The referenced placement intent does not exist."""


class PlacementRepairConflict(PlacementRepairError):
    """Durable state or ownership conflicts with the requested repair."""


class PlacementRepairInvalid(PlacementRepairError):
    """The repair request is malformed."""


class PlacementRepairService:
    """Resolve quarantined classic-DCA intents by lookup or dismissal.

    Terminal evidence is applied through the shared resume handler, so a
    repaired row reaches the identical local business state a normal startup
    recovery would produce. An intent whose exchange state cannot be proven
    stays quarantined until the operator either retries the lookup or records
    an explicit dismissal.
    """

    # One lock per operation serializes concurrent repair/dismiss attempts on
    # the same intent, so the second caller re-checks durable state after the
    # first one finishes instead of double-applying terminal evidence.
    _operation_locks: dict[str, asyncio.Lock] = {}

    def __init__(
        self,
        exchange: Any,
        intents: PlacementIntentService,
        resume_placement: Any,
    ) -> None:
        self.exchange = exchange
        self.intents = intents
        self.resume_placement = resume_placement

    @classmethod
    def _lock_for_operation(cls, operation_id: str) -> asyncio.Lock:
        """Return the process-wide lock serializing one operation's exits."""
        normalized = str(operation_id or "").strip()
        lock = cls._operation_locks.get(normalized)
        if lock is None:
            lock = asyncio.Lock()
            cls._operation_locks[normalized] = lock
        return lock

    async def list_quarantined(self) -> list[dict[str, Any]]:
        """Describe every intent that keeps the startup gate closed."""
        rows = await self.intents.list_action_required()
        return [await self._describe(row) for row in rows]

    async def repair(
        self,
        operation_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Look up one quarantined intent and apply its terminal evidence."""
        async with self._lock_for_operation(operation_id):
            result = await self._repair_locked(operation_id, config)
            self._evict_settled(operation_id, result)
            return result

    @classmethod
    def _evict_settled(cls, operation_id: str, result: dict[str, Any]) -> None:
        """Drop the per-operation lock once the intent is terminal.

        A terminal intent no longer mutates, so serializing it against
        itself is over; keeping the lock forever would grow the registry
        with one entry per operator repair for the process lifetime.
        """
        if str(result.get("status") or "") in TERMINAL_REPAIR_STATUSES:
            cls._operation_locks.pop(str(operation_id or "").strip(), None)

    async def _repair_locked(
        self,
        operation_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply one repair while the per-operation lock is held."""
        intent = await self._load_quarantined(operation_id)
        exchange_name = str(config.get("exchange") or "").strip()
        if not is_exchange_placement_enabled(config):
            return self._unchanged(
                intent,
                "No exchange is configured. Configure the exchange that owns "
                "this placement and retry, or dismiss it after manual review.",
            )
        if exchange_name.lower() != str(intent.exchange_name).strip().lower():
            return self._unchanged(
                intent,
                f"The configured exchange ({exchange_name}) does not match "
                f"the placement's exchange ({intent.exchange_name}). Repair "
                "with the matching credentials, or dismiss after manual "
                "review.",
            )
        if has_execution_scope(intent):
            if not placement_scope_matches(intent, config):
                return self._unchanged(
                    intent,
                    "The placement's verified account scope does not match "
                    f"the configured credentials ({exchange_name}). A lookup "
                    "could resolve against the wrong account; repair with "
                    "the matching credentials, or dismiss after manual "
                    "review.",
                )
        else:
            return self._unchanged(
                intent,
                "This legacy placement has no verified account scope, so a "
                "lookup cannot be bound to the account it was made on. "
                "Review the exchange manually and dismiss it when safe.",
            )
        if not intent.exchange_order_id and not intent.client_order_id:
            return self._unchanged(
                intent,
                "This placement has no durable exchange lookup identity "
                "(it was restored or interrupted before submission). Review "
                "the exchange manually and dismiss it when safe.",
            )
        lookup = await self._lookup(intent, config)
        if lookup.status == ExchangeOrderLookupStatus.NOT_FOUND:
            released = await self.intents.release_quarantine(
                str(intent.operation_id),
                PlacementIntentState.REJECTED,
                reason_code="operator_repair_identity_not_found",
                error_message=lookup.error_message,
            )
            return self._result(
                released,
                "rejected",
                "The exchange has no order under this placement's identity; "
                "the intent is recorded as rejected.",
            )
        if lookup.status != ExchangeOrderLookupStatus.FOUND or lookup.order is None:
            return self._unchanged(
                intent,
                "The exchange lookup is inconclusive "
                f"({lookup.error_message or 'no status'}). Retry when the "
                "exchange is reachable, or dismiss after manual review.",
            )
        return await self._apply_found_evidence(intent, lookup.order, config)

    async def dismiss(self, operation_id: str, note: str) -> dict[str, Any]:
        """Record one explicit operator dismissal as a terminal disposition."""
        async with self._lock_for_operation(operation_id):
            result = await self._dismiss_locked(operation_id, note)
            self._evict_settled(operation_id, result)
            return result

    async def _dismiss_locked(
        self,
        operation_id: str,
        note: str,
    ) -> dict[str, Any]:
        """Record one dismissal while the per-operation lock is held."""
        intent = await self._load_quarantined(operation_id)
        note_text = str(note or "").strip()
        if not note_text:
            raise PlacementRepairInvalid(
                "A dismissal note is required so the decision is auditable."
            )
        note_text = note_text[:MAX_DISMISS_NOTE_LENGTH]
        released = await self.intents.release_quarantine(
            str(intent.operation_id),
            PlacementIntentState.REJECTED,
            reason_code="operator_dismissed",
            error_message=f"Operator dismissal: {note_text}",
        )
        return self._result(
            released,
            "dismissed",
            "The operator dismissal was recorded; the intent is terminal and "
            "no longer blocks startup.",
        )

    async def _load_quarantined(self, operation_id: str) -> Any:
        normalized = str(operation_id or "").strip()
        if not normalized:
            raise PlacementRepairInvalid("A placement operation id is required.")
        intent = await self.intents.get(normalized)
        if intent is None:
            raise PlacementRepairNotFound(
                f"No placement intent found for {normalized}."
            )
        if str(intent.state) not in QUARANTINED_STATES:
            raise PlacementRepairConflict(
                f"Placement {normalized} is in state '{intent.state}', not quarantined."
            )
        decision = await load_lifecycle_route(str(intent.symbol))
        if decision.route != LifecycleRoute.CLASSIC_DCA:
            raise PlacementRepairConflict(
                "This placement belongs to accumulation; resolve it through "
                "the accumulation recovery flow."
            )
        return intent

    async def _lookup(
        self,
        intent: Any,
        config: dict[str, Any],
    ) -> ExchangeOrderLookupResult:
        try:
            async with asyncio.timeout(LOOKUP_TIMEOUT_SECONDS):
                return await self.exchange.lookup_spot_order(
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
        except (ccxt.BaseError, OSError, TimeoutError) as exc:
            logging.error(
                "Placement repair lookup failed for %s: %s",
                intent.operation_id,
                exc,
            )
            return ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.UNAVAILABLE,
                error_message=str(exc),
            )

    async def _apply_found_evidence(
        self,
        intent: Any,
        order: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Map one found order to the same terminal states the reconciler uses."""
        operation_id = str(intent.operation_id)
        action = str(intent.action)
        exchange_state = str(order.get("status") or "").strip().lower()
        if exchange_state in {"canceled", "cancelled", "rejected", "expired"}:
            if action == PlacementAction.CANCEL.value:
                if not await self._resume(intent, order, config):
                    return self._unchanged(
                        intent,
                        "The cancel is confirmed but its local effect could "
                        "not be resumed. Review the trade, then retry or "
                        "dismiss.",
                    )
                released = await self.intents.release_quarantine(
                    operation_id,
                    PlacementIntentState.COMPLETED,
                    reason_code="operator_repair_cancel_confirmed",
                    result=order,
                )
                return self._result(
                    released,
                    "completed",
                    "Confirmed cancel evidence was applied locally.",
                )
            if action == PlacementAction.BUY.value:
                buy_filled = validated_buy_filled_amount(order)
                if buy_filled is not None and buy_filled > 0:
                    if not await self._resume(intent, order, config):
                        return self._unchanged(
                            intent,
                            "The canceled order's partial fill could not be "
                            "resumed into local trade state. Review the "
                            "trade, then retry or dismiss.",
                        )
                    released = await self.intents.release_quarantine(
                        operation_id,
                        PlacementIntentState.COMPLETED,
                        reason_code="operator_repair_cancel_partial_fill_resumed",
                        result=order,
                    )
                    return self._result(
                        released,
                        "completed",
                        "The canceled order's partial fill was resumed into "
                        "local trade state.",
                    )
            released = await self.intents.release_quarantine(
                operation_id,
                PlacementIntentState.REJECTED,
                reason_code=f"operator_repair_exchange_order_{exchange_state}",
                error_message=lookup_error_from_order(order),
                exchange_order_id=str(order.get("id") or "") or None,
                result=order,
            )
            return self._result(
                released,
                "rejected",
                f"The exchange order is {exchange_state}; the intent is "
                "recorded as rejected.",
            )
        filled = float(order.get("filled") or 0.0)
        amount = float(order.get("amount") or 0.0)
        is_filled = exchange_state in {"closed", "filled"} or (
            amount > 0 and filled >= amount
        )
        if is_filled:
            if action == PlacementAction.BUY.value and filled <= 0:
                return self._unchanged(
                    intent,
                    "The exchange order is terminal but carries no fill "
                    "evidence. Verify the fill on the exchange and retry, "
                    "or dismiss.",
                )
            if not await self._resume(intent, order, config):
                return self._unchanged(
                    intent,
                    "The exchange fill could not be resumed into local trade "
                    "state (the matching trade may be gone). Review the "
                    "trade before dismissing.",
                )
            released = await self.intents.release_quarantine(
                operation_id,
                PlacementIntentState.COMPLETED,
                reason_code="operator_repair_fill_resumed",
                result=order,
            )
            return self._result(
                released,
                "completed",
                "Exchange fill evidence was applied and the trade finalized.",
            )
        if action == PlacementAction.LIMIT_SELL.value and exchange_state == "open":
            if not await self._resume(intent, order, config):
                return self._unchanged(
                    intent,
                    "The limit sell is still open but could not be re-attached "
                    "to an open trade. Review the trade before dismissing.",
                )
            released = await self.intents.release_quarantine(
                operation_id,
                PlacementIntentState.COMPLETED,
                reason_code="operator_repair_open_limit_reattached",
                result=order,
            )
            return self._result(
                released,
                "completed",
                "The open limit sell was re-attached to the trade.",
            )
        return self._unchanged(
            intent,
            f"The exchange order state '{exchange_state or 'unknown'}' has no "
            "definitive terminal mapping. Review the exchange, retry, or "
            "dismiss.",
        )

    async def _resume(
        self,
        intent: Any,
        order: dict[str, Any],
        config: dict[str, Any],
    ) -> bool:
        """Resume local persistence from found evidence, mirroring startup.

        The shared finalize seam documents that its callers guarantee
        exclusivity by holding the lifecycle mutation lock (at startup by
        reconciling before producers start), so acquire it here before the
        resume handler touches trade state.
        """
        try:
            async with lifecycle_mutation_coordinator.mutation(
                str(intent.symbol)
            ) as admitted:
                if not admitted:
                    logging.info(
                        "Placement repair resume for %s skipped during "
                        "trading maintenance.",
                        str(intent.operation_id),
                    )
                    return False
                return bool(await self.resume_placement(intent, order, config))
        except Exception as exc:  # noqa: BLE001 - a failure keeps quarantine.
            logging.error(
                "Placement repair resume failed for %s: %s",
                intent.operation_id,
                exc,
                exc_info=True,
            )
            return False

    async def _describe(self, intent: Any) -> dict[str, Any]:
        request = deserialize_placement_payload(intent.request_json)
        limit_price = (
            float(intent.maximum_price)
            if intent.maximum_price is not None
            else (
                float(request["limit_price"])
                if isinstance(request.get("limit_price"), (int, float))
                else None
            )
        )
        return {
            "operation_id": str(intent.operation_id),
            "symbol": str(intent.symbol),
            "action": str(intent.action),
            "side": str(intent.side),
            "order_type": str(intent.order_type),
            "state": str(intent.state),
            "exchange_name": str(intent.exchange_name),
            "reason_code": (str(intent.reason_code) if intent.reason_code else None),
            "error_message": (
                str(intent.error_message) if intent.error_message else None
            ),
            "exchange_order_id": (
                str(intent.exchange_order_id)
                if intent.exchange_order_id is not None
                else None
            ),
            "has_lookup_identity": bool(
                intent.exchange_order_id or intent.client_order_id
            ),
            "limit_price": limit_price,
            "amount": float(intent.requested_amount)
            if intent.requested_amount
            else None,
            "requested_quote": float(intent.requested_quote)
            if intent.requested_quote
            else None,
            "route": await self._route_name(str(intent.symbol)),
            "created_at": (
                intent.created_at.isoformat() if intent.created_at else None
            ),
            "completed_at": (
                intent.completed_at.isoformat() if intent.completed_at else None
            ),
        }

    @staticmethod
    async def _route_name(symbol: str) -> str:
        try:
            decision = await load_lifecycle_route(symbol)
            return str(decision.route)
        except Exception as exc:  # noqa: BLE001 - description stays readable.
            logging.warning("Lifecycle route unavailable for %s: %s", symbol, exc)
            return "unknown"

    @staticmethod
    def _unchanged(intent: Any, message: str) -> dict[str, Any]:
        return {
            "operation_id": str(intent.operation_id),
            "status": "unchanged",
            "state": str(intent.state),
            "message": message,
        }

    @staticmethod
    def _result(intent: Any, status: str, message: str) -> dict[str, Any]:
        return {
            "operation_id": str(intent.operation_id),
            "status": status,
            "state": str(intent.state),
            "message": message,
        }


def validated_buy_filled_amount(order: dict[str, Any]) -> float | None:
    """Return a validated non-negative buy fill amount, or ``None``.

    Mirrors the startup reconciler's buy fill evidence check so the
    operator repair path and startup reconciliation reject the same
    malformed evidence: missing, boolean, non-numeric, non-finite or
    negative fills all count as "no valid fill evidence".
    """
    raw_filled = order.get("filled")
    if raw_filled is None or isinstance(raw_filled, bool):
        return None
    try:
        filled = float(raw_filled)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(filled) or filled < 0:
        return None
    return filled


def lookup_error_from_order(order: dict[str, Any]) -> str | None:
    """Return a stored exchange-side error note when the order carries one."""
    error = order.get("error_message") or order.get("error")
    return str(error) if error else None
