"""Durable state and portability rules for exchange placement intents."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

import helper
import model
from service.database import run_sqlite_write_with_retry
from service.exchange_capabilities import build_client_order_id
from tortoise.exceptions import IntegrityError

logging = helper.LoggerFactory.get_logger(
    "logs/placement_intents.log",
    "placement_intents",
)


class PlacementIntentState(StrEnum):
    """Durable states for every exchange-side placement or cancellation."""

    PREPARED = "prepared"
    SUBMITTING = "submitting"
    REJECTED = "rejected"
    INDETERMINATE = "indeterminate"
    RECONCILING = "reconciling"
    ACCEPTED = "accepted"
    FILLED = "filled"
    PERSISTED = "persisted"
    COMPLETED = "completed"
    QUARANTINED = "quarantined"
    RESTORED_QUARANTINED = "restored_quarantined"


class PlacementAction(StrEnum):
    """Exchange effects that require durable identity and reconciliation."""

    BUY = "buy"
    SELL = "sell"
    LIMIT_SELL = "limit_sell"
    CANCEL = "cancel"


TERMINAL_PLACEMENT_STATES = frozenset(
    {
        PlacementIntentState.REJECTED.value,
        PlacementIntentState.COMPLETED.value,
        PlacementIntentState.QUARANTINED.value,
        PlacementIntentState.RESTORED_QUARANTINED.value,
    }
)
NONTERMINAL_PLACEMENT_STATES = frozenset(
    state.value
    for state in PlacementIntentState
    if state.value not in TERMINAL_PLACEMENT_STATES
)
EXPOSURE_PLACEMENT_ACTIONS = frozenset(
    {
        PlacementAction.BUY.value,
        PlacementAction.SELL.value,
        PlacementAction.LIMIT_SELL.value,
    }
)

_VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    PlacementIntentState.PREPARED.value: frozenset(
        {
            PlacementIntentState.SUBMITTING.value,
            PlacementIntentState.REJECTED.value,
            PlacementIntentState.QUARANTINED.value,
        }
    ),
    PlacementIntentState.SUBMITTING.value: frozenset(
        {
            PlacementIntentState.REJECTED.value,
            PlacementIntentState.INDETERMINATE.value,
            PlacementIntentState.ACCEPTED.value,
            PlacementIntentState.FILLED.value,
            PlacementIntentState.QUARANTINED.value,
        }
    ),
    PlacementIntentState.INDETERMINATE.value: frozenset(
        {
            PlacementIntentState.RECONCILING.value,
            PlacementIntentState.QUARANTINED.value,
        }
    ),
    PlacementIntentState.RECONCILING.value: frozenset(
        {
            PlacementIntentState.REJECTED.value,
            PlacementIntentState.ACCEPTED.value,
            PlacementIntentState.FILLED.value,
            PlacementIntentState.QUARANTINED.value,
        }
    ),
    PlacementIntentState.ACCEPTED.value: frozenset(
        {
            PlacementIntentState.RECONCILING.value,
            PlacementIntentState.FILLED.value,
            PlacementIntentState.PERSISTED.value,
            PlacementIntentState.QUARANTINED.value,
        }
    ),
    PlacementIntentState.FILLED.value: frozenset(
        {
            PlacementIntentState.PERSISTED.value,
            PlacementIntentState.QUARANTINED.value,
        }
    ),
    PlacementIntentState.PERSISTED.value: frozenset(
        {
            PlacementIntentState.COMPLETED.value,
            PlacementIntentState.QUARANTINED.value,
        }
    ),
}

_SAFE_REQUEST_KEYS = frozenset(
    {
        "symbol",
        "side",
        "ordertype",
        "ordersize",
        "amount",
        "total_amount",
        "requested_total_amount",
        "total_cost",
        "actual_pnl",
        "maximum_buy_price",
        "limit_price",
        "current_price",
        "baseorder",
        "safetyorder",
        "order_count",
        "campaign_id",
        "deal_id",
        "sell_reason",
        "type_sell",
        "direction",
        "botname",
        "metadata_json",
        "source_operation_id",
    }
)


@dataclass(frozen=True)
class PlacementPreparation:
    """Result of preparing or deduplicating one durable operation."""

    intent: Any | None
    operation_id: str | None
    client_order_id: str | None
    blocked_by_conflict: bool = False


def is_live_placement_enabled(config: dict[str, Any]) -> bool:
    """Return whether the request can cause an external exchange side effect."""
    return bool(str(config.get("exchange") or "").strip()) and not bool(
        config.get("dry_run", True)
    )


def ensure_operation_id(
    order: dict[str, Any],
    action: PlacementAction | str,
) -> str:
    """Attach and return a durable operation identity for one effect."""
    existing = str(order.get("operation_id") or "").strip()
    if existing:
        return existing
    operation_id = f"{str(action)}-{uuid4().hex}"
    order["operation_id"] = operation_id
    return operation_id


def build_derived_operation_id(
    action: PlacementAction | str,
    *identity_parts: Any,
) -> str:
    """Build a stable operation id for an effect tied to durable identities."""
    identity = ":".join(str(part or "").strip() for part in identity_parts)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:48]
    return f"{str(action)}-{digest}"


def _safe_request_payload(order: dict[str, Any]) -> dict[str, Any]:
    """Return the allow-listed, JSON-safe portion of an exchange request."""
    payload: dict[str, Any] = {}
    for key in _SAFE_REQUEST_KEYS:
        if key not in order:
            continue
        value = order[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            payload[key] = value
    return payload


def serialize_placement_payload(payload: Any) -> str:
    """Serialize exchange evidence without allowing non-JSON runtime objects."""
    return json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))


def deserialize_placement_payload(raw_value: Any) -> dict[str, Any]:
    """Return one persisted request/result payload as a mapping."""
    if not isinstance(raw_value, str) or not raw_value.strip():
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


class PlacementIntentService:
    """Persist exchange effects before submission and advance them monotonically."""

    _lock = asyncio.Lock()

    async def prepare(
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
    ) -> PlacementPreparation:
        """Create the durable intent, or return the existing operation safely."""
        if not is_live_placement_enabled(config):
            return PlacementPreparation(
                intent=None,
                operation_id=None,
                client_order_id=None,
            )

        operation_id = ensure_operation_id(order, action)
        client_order_id = build_client_order_id(operation_id)
        exchange_name = str(config.get("exchange") or "").strip().lower()
        symbol = str(order.get("symbol") or "").strip()
        normalized_action = str(action)
        normalized_side = str(side).strip().lower()
        normalized_order_type = str(order_type).strip().lower()
        request_json = serialize_placement_payload(_safe_request_payload(order))

        async with self._lock:

            async def _prepare() -> Any:
                existing = await model.PlacementIntent.get_or_none(
                    operation_id=operation_id
                )
                if existing is not None:
                    self._validate_existing(
                        existing,
                        exchange_name=exchange_name,
                        symbol=symbol,
                        action=normalized_action,
                        side=normalized_side,
                        order_type=normalized_order_type,
                        source_operation_id=(
                            str(order.get("source_operation_id") or "").strip() or None
                        ),
                    )
                    return existing
                conflicting_actions = (
                    sorted(EXPOSURE_PLACEMENT_ACTIONS)
                    if normalized_action in EXPOSURE_PLACEMENT_ACTIONS
                    else [normalized_action]
                )
                pending_query = model.PlacementIntent.filter(
                    exchange_name=exchange_name,
                    symbol=symbol,
                    action__in=conflicting_actions,
                    state__in=sorted(NONTERMINAL_PLACEMENT_STATES),
                )
                source_operation_id = str(
                    order.get("source_operation_id") or ""
                ).strip()
                if (
                    normalized_action == PlacementAction.SELL.value
                    and source_operation_id
                ):
                    source = await model.PlacementIntent.get_or_none(
                        operation_id=source_operation_id
                    )
                    if (
                        source is not None
                        and str(source.exchange_name) == exchange_name
                        and str(source.symbol) == symbol
                        and str(source.action) == PlacementAction.LIMIT_SELL.value
                        and str(source.state) == PlacementIntentState.FILLED.value
                    ):
                        pending_query = pending_query.exclude(
                            operation_id=source_operation_id
                        )
                pending = await pending_query.order_by("created_at").first()
                if pending is not None:
                    return pending
                try:
                    return await model.PlacementIntent.create(
                        operation_id=operation_id,
                        source_operation_id=(
                            str(order.get("source_operation_id") or "").strip() or None
                        ),
                        client_order_id=client_order_id,
                        exchange_order_id=exchange_order_id,
                        exchange_name=exchange_name,
                        symbol=symbol,
                        action=normalized_action,
                        side=normalized_side,
                        order_type=normalized_order_type,
                        state=PlacementIntentState.PREPARED.value,
                        deal_id=str(order.get("deal_id") or "").strip() or None,
                        campaign_id=(
                            str(order.get("campaign_id") or "").strip() or None
                        ),
                        requested_quote=max(0.0, float(requested_quote or 0.0)),
                        requested_amount=max(0.0, float(requested_amount or 0.0)),
                        maximum_price=(
                            float(order["maximum_buy_price"])
                            if float(order.get("maximum_buy_price") or 0.0) > 0
                            else (
                                float(order["limit_price"])
                                if float(order.get("limit_price") or 0.0) > 0
                                else None
                            )
                        ),
                        reserved_quote=max(0.0, float(reserved_quote or 0.0)),
                        request_json=request_json,
                    )
                except IntegrityError:
                    concurrent = await model.PlacementIntent.get(
                        operation_id=operation_id
                    )
                    self._validate_existing(
                        concurrent,
                        exchange_name=exchange_name,
                        symbol=symbol,
                        action=normalized_action,
                        side=normalized_side,
                        order_type=normalized_order_type,
                        source_operation_id=(
                            str(order.get("source_operation_id") or "").strip() or None
                        ),
                    )
                    return concurrent

            intent = await run_sqlite_write_with_retry(
                _prepare,
                f"preparing placement intent {operation_id}",
            )

        resolved_operation_id = str(intent.operation_id)
        resolved_client_order_id = str(
            intent.client_order_id or build_client_order_id(resolved_operation_id)
        )
        blocked_by_conflict = resolved_operation_id != operation_id
        if not blocked_by_conflict:
            order["operation_id"] = resolved_operation_id
            order["client_order_id"] = resolved_client_order_id
        return PlacementPreparation(
            intent=intent,
            operation_id=resolved_operation_id,
            client_order_id=resolved_client_order_id,
            blocked_by_conflict=blocked_by_conflict,
        )

    async def transition(
        self,
        operation_id: str | None,
        target: PlacementIntentState | str,
        *,
        exchange_order_id: str | None = None,
        result: dict[str, Any] | None = None,
        reason_code: str | None = None,
        error_message: str | None = None,
    ) -> Any | None:
        """Advance an intent through one validated durable transition."""
        if not operation_id:
            return None
        target_state = str(target)

        async with self._lock:

            async def _transition() -> Any:
                intent = await model.PlacementIntent.get(operation_id=operation_id)
                current_state = str(intent.state)
                if current_state == target_state:
                    return intent
                allowed = _VALID_TRANSITIONS.get(current_state, frozenset())
                if target_state not in allowed:
                    raise ValueError(
                        f"Invalid placement transition {current_state} -> "
                        f"{target_state} for {operation_id}"
                    )

                intent.state = target_state
                update_fields = ["state", "updated_at"]
                if exchange_order_id:
                    intent.exchange_order_id = str(exchange_order_id)
                    update_fields.append("exchange_order_id")
                if result is not None:
                    intent.result_json = serialize_placement_payload(result)
                    update_fields.append("result_json")
                if reason_code is not None:
                    intent.reason_code = str(reason_code)
                    update_fields.append("reason_code")
                if error_message is not None:
                    intent.error_message = str(error_message)
                    update_fields.append("error_message")
                now = datetime.now(timezone.utc)
                if target_state == PlacementIntentState.SUBMITTING.value:
                    intent.submitted_at = now
                    update_fields.append("submitted_at")
                if target_state in TERMINAL_PLACEMENT_STATES:
                    intent.completed_at = now
                    update_fields.append("completed_at")
                await intent.save(update_fields=update_fields)
                return intent

            return await run_sqlite_write_with_retry(
                _transition,
                f"transitioning placement intent {operation_id} to {target_state}",
            )

    async def claim_submission(self, operation_id: str | None) -> bool:
        """Atomically claim the sole right to submit a prepared operation."""
        if not operation_id:
            return True
        async with self._lock:

            async def _claim() -> bool:
                intent = await model.PlacementIntent.get(operation_id=operation_id)
                if str(intent.state) != PlacementIntentState.PREPARED.value:
                    return False
                intent.state = PlacementIntentState.SUBMITTING.value
                intent.submitted_at = datetime.now(timezone.utc)
                await intent.save(update_fields=["state", "submitted_at", "updated_at"])
                return True

            return bool(
                await run_sqlite_write_with_retry(
                    _claim,
                    f"claiming placement intent {operation_id}",
                )
            )

    async def mark_reconciling(self, operation_id: str) -> Any:
        """Increment reconciliation attempts and enter the reconciling state."""
        intent = await self.transition(
            operation_id,
            PlacementIntentState.RECONCILING,
        )
        if intent is None:
            raise ValueError("A durable operation id is required for reconciliation")
        intent.reconciliation_attempts = int(intent.reconciliation_attempts or 0) + 1
        await intent.save(update_fields=["reconciliation_attempts", "updated_at"])
        return intent

    @staticmethod
    async def list_nonterminal() -> list[Any]:
        """Return all operations that startup must reconcile or quarantine."""
        return await model.PlacementIntent.filter(
            state__in=sorted(NONTERMINAL_PLACEMENT_STATES)
        ).order_by("created_at")

    @staticmethod
    async def list_action_required() -> list[Any]:
        """Return quarantined operations that keep startup fail-closed."""
        return await model.PlacementIntent.filter(
            state__in=[
                PlacementIntentState.QUARANTINED.value,
                PlacementIntentState.RESTORED_QUARANTINED.value,
            ]
        ).order_by("created_at")

    @staticmethod
    async def get(operation_id: str) -> Any | None:
        """Return one durable operation by its external identity."""
        return await model.PlacementIntent.get_or_none(operation_id=operation_id)

    @staticmethod
    def _validate_existing(
        intent: Any,
        *,
        exchange_name: str,
        symbol: str,
        action: str,
        side: str,
        order_type: str,
        source_operation_id: str | None,
    ) -> None:
        """Reject accidental reuse of an operation identity for another effect."""
        expected = (
            exchange_name,
            symbol,
            action,
            side,
            order_type,
            source_operation_id,
        )
        actual = (
            str(intent.exchange_name),
            str(intent.symbol),
            str(intent.action),
            str(intent.side),
            str(intent.order_type),
            (
                str(intent.source_operation_id)
                if intent.source_operation_id is not None
                else None
            ),
        )
        if actual != expected:
            raise ValueError(
                "Placement operation id was reused with a different request: "
                f"expected={actual} received={expected}"
            )


async def mark_placement_persisted_in_transaction(
    operation_id: str | None,
    connection: Any,
) -> None:
    """Atomically mark local business persistence in its owning transaction."""
    await mark_placements_persisted_in_transaction([operation_id], connection)


async def mark_placements_persisted_in_transaction(
    operation_ids: list[str | None],
    connection: Any,
) -> None:
    """Atomically mark every placement represented by one business write."""
    normalized_ids = list(
        dict.fromkeys(
            str(operation_id).strip()
            for operation_id in operation_ids
            if str(operation_id or "").strip()
        )
    )
    for operation_id in normalized_ids:
        updated = (
            await model.PlacementIntent.filter(
                operation_id=operation_id,
                state__in=[
                    PlacementIntentState.ACCEPTED.value,
                    PlacementIntentState.FILLED.value,
                ],
            )
            .using_db(connection)
            .update(state=PlacementIntentState.PERSISTED.value)
        )
        if updated == 1:
            continue
        intent = (
            await model.PlacementIntent.filter(operation_id=operation_id)
            .using_db(connection)
            .first()
        )
        state = str(intent.state) if intent is not None else "missing"
        raise ValueError(
            f"Cannot mark placement {operation_id} persisted from state {state}"
        )


def is_terminal_placement_state(value: Any) -> bool:
    """Return whether a persisted intent is safe as portable audit history."""
    return str(value or "").strip() in TERMINAL_PLACEMENT_STATES


def quarantine_restored_intent(row: dict[str, Any]) -> dict[str, Any]:
    """Invalidate external identity and quarantine a restored nonterminal intent."""
    source_operation_id = str(row.get("operation_id") or "").strip()
    restored = dict(row)
    restored.pop("id", None)
    restored["operation_id"] = f"restored-{uuid4()}"
    restored["source_operation_id"] = source_operation_id or None
    restored["client_order_id"] = None
    restored["exchange_order_id"] = None
    restored["state"] = PlacementIntentState.RESTORED_QUARANTINED.value
    restored["result_json"] = None
    restored["reason_code"] = "portable_restore_quarantine"
    restored["error_message"] = (
        "The source placement was nonterminal. It will not be submitted from "
        "this restored installation; reconcile it manually."
    )
    restored["reconciliation_attempts"] = 0
    restored["submitted_at"] = None
    restored["completed_at"] = None
    restored.pop("created_at", None)
    restored.pop("updated_at", None)
    return restored
