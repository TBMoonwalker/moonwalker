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
import json
import math
from collections.abc import Callable
from typing import Any

import ccxt.async_support as ccxt
import helper
from service.exchange_capabilities import (
    ExchangeOrderLookupResult,
    ExchangeOrderLookupStatus,
    exchange_execution_scope,
)
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.lifecycle_routing import LifecycleRoute, load_lifecycle_route
from service.placement_intents import (
    PlacementAction,
    PlacementIntentService,
    PlacementIntentState,
    QuarantineResolution,
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
        *,
        config_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Look up one quarantined intent and apply its terminal evidence."""
        async with self._lock_for_operation(operation_id):
            result = await self._repair_locked(operation_id, config, config_provider)
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
        config_provider: Callable[[], dict[str, Any]] | None,
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
        provider = config_provider or (lambda: config)
        if not placement_scope_matches(intent, provider()):
            return self._unchanged(
                intent,
                "The exchange account scope changed during lookup. Retry with the correct account.",
            )
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
        order = lookup.order
        if not placement_lookup_identity_matches(intent, order):
            return self._unchanged(
                intent,
                "The exchange response does not verify the placement identity.",
            )
        return await self._apply_found_evidence(intent, order, config, provider)

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
        config_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Map one found order to the same terminal states the reconciler uses."""
        operation_id = str(intent.operation_id)
        action = str(intent.action)
        exchange_state = str(order.get("status") or "").strip().lower()
        if exchange_state in {"canceled", "cancelled", "rejected", "expired"}:
            if action == PlacementAction.CANCEL.value:
                if not has_reliable_cancel_evidence(intent, order):
                    return self._unchanged(
                        intent,
                        "The canceled order has no reliable fill amount or proceeds. "
                        "Review the exchange order before resolving it.",
                    )
                if not await self._resume(
                    intent,
                    order,
                    config,
                    "operator_repair_cancel_confirmed",
                    config_provider,
                ):
                    return self._unchanged(
                        intent,
                        "The cancel is confirmed but its local effect could "
                        "not be resumed. Review the trade, then retry or "
                        "dismiss.",
                    )
                released = await self.intents.get(operation_id)
                return self._result(
                    released,
                    "completed",
                    "Confirmed cancel evidence was applied locally.",
                )
            if action == PlacementAction.BUY.value:
                buy_filled = validated_buy_filled_amount(order)
                if buy_filled is None:
                    return self._unchanged(
                        intent,
                        "The canceled order has no reliable fill amount. "
                        "Review the exchange order before resolving it.",
                    )
                if buy_filled is not None and buy_filled > 0:
                    if not await self._resume(
                        intent,
                        order,
                        config,
                        "operator_repair_cancel_partial_fill_resumed",
                        config_provider,
                    ):
                        return self._unchanged(
                            intent,
                            "The canceled order's partial fill could not be "
                            "resumed into local trade state. Review the "
                            "trade, then retry or dismiss.",
                        )
                    released = await self.intents.get(operation_id)
                    return self._result(
                        released,
                        "completed",
                        "The canceled order's partial fill was resumed into "
                        "local trade state.",
                    )
            if action in {PlacementAction.SELL.value, PlacementAction.LIMIT_SELL.value}:
                sell_filled = validated_buy_filled_amount(order)
                if sell_filled is None or sell_filled > 0:
                    return self._unchanged(
                        intent,
                        "The canceled sell may have a fill that needs manual "
                        "reconciliation. Review the exchange order before resolving it.",
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
        filled_value = validated_buy_filled_amount(order)
        amount_value = validated_buy_filled_amount({"filled": order.get("amount")})
        filled = filled_value if filled_value is not None else 0.0
        amount = amount_value if amount_value is not None else 0.0
        is_filled = exchange_state in {"closed", "filled"} or (
            amount > 0 and filled >= amount
        )
        if is_filled:
            if action == PlacementAction.BUY.value and (
                filled_value is None or filled <= 0
            ):
                return self._unchanged(
                    intent,
                    "The exchange order is terminal but carries no fill "
                    "evidence. Verify the fill on the exchange and retry, "
                    "or dismiss.",
                )
            if action in {
                PlacementAction.SELL.value,
                PlacementAction.LIMIT_SELL.value,
                PlacementAction.CANCEL.value,
            }:
                if not (
                    has_complete_sell_fill(intent, order)
                    or (
                        action != PlacementAction.CANCEL.value
                        and has_terminal_partial_sell(intent, order)
                    )
                ) or (
                    action == PlacementAction.CANCEL.value
                    and not has_confirmed_sell_proceeds(order)
                ):
                    return self._unchanged(
                        intent,
                        "The exchange evidence does not prove a complete sell fill. "
                        "Review the order before resolving it.",
                    )
            if not await self._resume(
                intent, order, config, "operator_repair_fill_resumed", config_provider
            ):
                return self._unchanged(
                    intent,
                    "The exchange fill could not be resumed into local trade "
                    "state (the matching trade may be gone). Review the "
                    "trade before dismissing.",
                )
            released = await self.intents.get(operation_id)
            message = (
                "Exchange fill evidence was applied; the remaining position stays open."
                if action != PlacementAction.CANCEL.value
                and has_terminal_partial_sell(intent, order)
                else "Exchange fill evidence was applied and the trade finalized."
            )
            return self._result(
                released,
                "completed",
                message,
            )
        if action == PlacementAction.LIMIT_SELL.value and exchange_state == "open":
            if not str(order.get("id") or intent.exchange_order_id or "").strip():
                return self._unchanged(
                    intent,
                    "The open limit sell has no exchange order ID. "
                    "Review the exchange order before resolving it.",
                )
            if not await self._resume(
                intent,
                order,
                config,
                "operator_repair_open_limit_reattached",
                config_provider,
            ):
                return self._unchanged(
                    intent,
                    "The limit sell is still open but could not be re-attached "
                    "to an open trade. Review the trade before dismissing.",
                )
            released = await self.intents.get(operation_id)
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
        reason_code: str,
        config_provider: Callable[[], dict[str, Any]] | None,
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
                current = await self.intents.get(str(intent.operation_id))
                if (
                    current is None
                    or str(current.state) not in QUARANTINED_STATES
                    or current.request_json != intent.request_json
                    or any(
                        getattr(current, field) != getattr(intent, field)
                        for field in (
                            "symbol",
                            "action",
                            "exchange_name",
                            "deal_id",
                            "exchange_order_id",
                            "client_order_id",
                        )
                    )
                    or not placement_scope_matches(
                        current, (config_provider or (lambda: config))()
                    )
                    or (await load_lifecycle_route(str(current.symbol))).route
                    != LifecycleRoute.CLASSIC_DCA
                ):
                    return False
                resolution = QuarantineResolution(
                    operation_id=str(current.operation_id),
                    request_json=str(current.request_json),
                    symbol=str(current.symbol),
                    action=str(current.action),
                    exchange_name=str(current.exchange_name),
                    expected_exchange_order_id=(
                        str(current.exchange_order_id)
                        if current.exchange_order_id is not None
                        else None
                    ),
                    client_order_id=(
                        str(current.client_order_id)
                        if current.client_order_id is not None
                        else None
                    ),
                    exchange_order_id=(
                        str(order.get("id") or current.exchange_order_id)
                        if order.get("id") or current.exchange_order_id
                        else None
                    ),
                    deal_id=str(current.deal_id) if current.deal_id else None,
                    base_buy=(
                        str(current.action) == PlacementAction.BUY.value
                        and bool(
                            deserialize_placement_payload(current.request_json).get(
                                "baseorder"
                            )
                        )
                    ),
                    execution_scope=exchange_execution_scope(config),
                    config_provider=config_provider or (lambda: config),
                    reason_code=reason_code,
                    result=dict(order),
                )
                await self.resume_placement(
                    current, order, config, resolution=resolution
                )
        except Exception as exc:  # noqa: BLE001 - a failure keeps quarantine.
            logging.error(
                "Placement repair resume failed for %s: %s",
                intent.operation_id,
                exc,
                exc_info=True,
            )
        current = await self.intents.get(str(intent.operation_id))
        return bool(
            current is not None
            and str(current.state) == PlacementIntentState.COMPLETED.value
            and current.reason_code == reason_code
        )

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
            "client_order_id": (
                str(intent.client_order_id)
                if intent.client_order_id is not None
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


def placement_lookup_identity_matches(intent: Any, order: dict[str, Any]) -> bool:
    """Verify lookup evidence against the durable exchange or client identity."""
    if order.get("symbol") is not None and order["symbol"] != intent.symbol:
        return False
    if order.get("side") is not None and (
        str(order["side"]).strip().lower() != str(intent.side).strip().lower()
    ):
        return False
    exchange_id = str(intent.exchange_order_id or "").strip()
    if exchange_id:
        return str(order.get("id") or "").strip() == exchange_id
    expected_client_id = str(intent.client_order_id or "").strip()
    if not expected_client_id:
        return False
    info = order.get("info")
    info = info if isinstance(info, dict) else {}
    client_id = (
        order.get("clientOrderId")
        or info.get("orderLinkId")
        or info.get("clientOrderId")
        or info.get("origClientOrderId")
    )
    return str(client_id or "").strip() == expected_client_id


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


def has_confirmed_sell_proceeds(order: dict[str, Any]) -> bool:
    """Require positive finite execution cost or average for a partial fill."""
    filled = validated_buy_filled_amount(order)
    if filled is None or filled <= 0:
        return False
    selected_price = order.get("average") or order.get("price")
    price = 0.0
    if selected_price is not None:
        if isinstance(selected_price, bool):
            return False
        try:
            price = float(selected_price)
            if not math.isfinite(price):
                return False
        except (TypeError, ValueError):
            return False
    cost = order.get("cost")
    if cost is not None:
        if isinstance(cost, bool):
            return False
        try:
            parsed_cost = float(cost)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(parsed_cost) or parsed_cost < 0:
            return False
        if parsed_cost > 0:
            derived_price = parsed_cost / filled
            return math.isfinite(derived_price) and derived_price > 0
    return (
        bool(order.get("average"))
        and price > 0
        and math.isfinite(filled * price)
        and filled * price > 0
    )


def has_reliable_cancel_evidence(intent: Any, order: dict[str, Any]) -> bool:
    """Require consistent cancellation quantities and real partial proceeds."""
    filled = validated_buy_filled_amount(order)
    requested = validated_buy_filled_amount({"filled": intent.requested_amount})
    amount = validated_buy_filled_amount({"filled": order.get("amount")})
    return bool(
        filled is not None
        and requested is not None
        and requested > 0
        and filled <= requested
        and (order.get("amount") is None or amount == requested)
        and (filled == 0 or has_confirmed_sell_proceeds(order))
    )


def has_complete_sell_fill(intent: Any, order: dict[str, Any]) -> bool:
    """Require the confirmed fill to cover the durable sell quantity."""
    filled = validated_buy_filled_amount(order)
    requested = validated_buy_filled_amount({"filled": intent.requested_amount})
    amount = validated_buy_filled_amount({"filled": order.get("amount")})
    return bool(
        filled is not None
        and requested is not None
        and requested > 0
        and filled == requested
        and (order.get("amount") is None or amount == requested)
    )


def has_valid_stored_full_sell(intent: Any, order: dict[str, Any]) -> bool:
    """Verify normalized sell values against their durable execution report."""
    try:
        metadata = json.loads(order.get("metadata_json") or "")
        report = metadata["execution_report"]
        if not isinstance(report, dict):
            return False
        identity = str(intent.exchange_order_id or "").strip()
        requested = validated_buy_filled_amount({"filled": intent.requested_amount})
        filled = validated_buy_filled_amount({"filled": report.get("filled")})
        amount = validated_buy_filled_amount({"filled": order.get("total_amount")})
        cost = float(report["quote_cost"])
        proceeds = float(order["ordersize"])
        price = float(order["price"])
        return bool(
            identity
            and report.get("order_id") == identity
            and str(order.get("orderid") or "") == identity
            and report.get("symbol") == order.get("symbol") == intent.symbol
            and report.get("side") == order.get("side") == "sell"
            and report.get("terminal") is True
            and requested is not None
            and requested > 0
            and filled == requested == amount
            and math.isfinite(cost)
            and cost > 0
            and math.isfinite(proceeds)
            and math.isfinite(price)
            and price > 0
            and math.isclose(cost, proceeds, rel_tol=1e-8)
            and math.isclose(cost, price * amount, rel_tol=1e-8)
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def has_valid_stored_partial_sell(intent: Any, order: dict[str, Any]) -> bool:
    """Validate one durable normalized partial before replaying its local effect."""
    if order.get("type") != "partial_sell" and not (
        order.get("requires_market_fallback") is True
        and order.get("limit_cancel_confirmed") is True
    ):
        return False
    if order.get("unsellable") or order.get("symbol") != intent.symbol:
        return False
    if not str(intent.deal_id or "").strip():
        return False
    identity = str(intent.exchange_order_id or "").strip()
    executions = order.get("executions")
    if not identity or not isinstance(executions, list) or len(executions) != 1:
        return False
    execution = executions[0]
    if not isinstance(execution, dict):
        return False
    if (
        str(execution.get("order_id") or "").strip() != identity
        or execution.get("symbol") != intent.symbol
        or str(execution.get("side") or "").lower() != "sell"
    ):
        return False
    if order.get("exchange_order_id") not in (None, identity):
        return False
    amount = validated_buy_filled_amount({"filled": order.get("partial_filled_amount")})
    remaining = validated_buy_filled_amount({"filled": order.get("remaining_amount")})
    requested = validated_buy_filled_amount({"filled": intent.requested_amount})
    price = validated_buy_filled_amount({"filled": order.get("partial_avg_price")})
    execution_amount = validated_buy_filled_amount({"filled": execution.get("amount")})
    execution_price = validated_buy_filled_amount({"filled": execution.get("price")})
    proceeds = validated_buy_filled_amount({"filled": execution.get("ordersize")})
    fee = validated_buy_filled_amount({"filled": execution.get("fee", 0)})
    if any(
        value is None
        for value in (
            amount,
            remaining,
            requested,
            price,
            execution_amount,
            execution_price,
            proceeds,
            fee,
        )
    ):
        return False
    assert amount is not None and remaining is not None and requested is not None
    assert (
        price is not None
        and execution_amount is not None
        and execution_price is not None
        and proceeds is not None
    )
    if amount <= 0 or remaining <= 0 or requested <= 0 or price <= 0 or proceeds <= 0:
        return False
    if not math.isfinite(amount * price):
        return False
    if not all(
        (
            math.isclose(amount + remaining, requested, rel_tol=1e-9),
            math.isclose(execution_amount, amount, rel_tol=1e-12),
            math.isclose(execution_price, price, rel_tol=1e-8),
            math.isclose(proceeds, amount * price, rel_tol=1e-8),
        )
    ):
        return False
    if order.get("partial_proceeds") is not None:
        recorded = validated_buy_filled_amount({"filled": order["partial_proceeds"]})
        if recorded is None or not math.isclose(recorded, proceeds, rel_tol=1e-8):
            return False
    return True


def has_terminal_partial_sell(intent: Any, order: dict[str, Any]) -> bool:
    """Prove a submitted terminal sell filled less than the original exposure."""
    filled = validated_buy_filled_amount(order)
    requested = validated_buy_filled_amount({"filled": intent.requested_amount})
    amount = validated_buy_filled_amount({"filled": order.get("amount")})
    return bool(
        str(order.get("status") or "").lower() in {"closed", "filled"}
        and filled is not None
        and amount is not None
        and requested is not None
        and 0 < filled == amount < requested
        and bool(str(order.get("id") or "").strip())
        and (not order.get("symbol") or order["symbol"] == intent.symbol)
        and (not order.get("side") or str(order["side"]).lower() == "sell")
        and has_confirmed_sell_proceeds(order)
    )


def lookup_error_from_order(order: dict[str, Any]) -> str | None:
    """Return a stored exchange-side error note when the order carries one."""
    error = order.get("error_message") or order.get("error")
    return str(error) if error else None
