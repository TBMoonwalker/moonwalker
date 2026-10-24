"""Shared orchestration for claiming and advancing durable exchange effects."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import ccxt.async_support as ccxt
import helper
from service.exchange_capabilities import (
    ExchangePostSubmissionFailure,
    ExchangeSubmissionIndeterminate,
)
from service.placement_intents import (
    PlacementAction,
    PlacementIntentService,
    PlacementIntentState,
    placement_scope_matches,
)

logging = helper.LoggerFactory.get_logger("logs/orders.log", "orders")


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
        if not placement_scope_matches(preparation.intent, config):
            return PlacementStart(
                status=PlacementStartStatus.BLOCKED,
                operation_id=preparation.operation_id,
                client_order_id=preparation.client_order_id,
                state="scope_unverified",
            )
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

    async def submit(
        self,
        operation_id: str | None,
        *,
        symbol: str,
        side: str,
        submit: Callable[[], Awaitable[Any]],
        require_acknowledgement: bool = False,
    ) -> dict[str, Any] | None:
        """Submit one already claimed effect and durably retain its acknowledgement.

        The caller owns mode-specific atomic admission and accounting. Transport
        uncertainty never grants permission to resend. Legacy adapters may return
        an empty result after a proven rejection or confirmed zero-fill cancel;
        raw exchange adapters must return an acknowledgement identity.
        """
        logging.info(
            "Order submitting operation=%s symbol=%s side=%s",
            operation_id,
            symbol,
            side,
        )
        try:
            result = await submit()
        except asyncio.CancelledError:
            # SUBMITTING remains durable even if cancellation interrupts storage.
            logging.warning(
                "Order requires reconciliation operation=%s symbol=%s side=%s failure=CancelledError",
                operation_id,
                symbol,
                side,
            )
            raise
        except ExchangePostSubmissionFailure as exc:
            await self.intents.transition(
                exc.operation_id or operation_id,
                PlacementIntentState.ACCEPTED,
                exchange_order_id=str(exc.order.get("id") or "") or None,
                result=exc.order,
                reason_code="local_finalization_pending",
            )
            logging.warning(
                "Order accepted; accounting pending operation=%s symbol=%s side=%s",
                exc.operation_id or operation_id,
                symbol,
                side,
            )
            raise
        except (
            ExchangeSubmissionIndeterminate,
            ccxt.BaseError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
        ) as exc:
            active = getattr(exc, "operation_id", None) or operation_id
            await self.intents.transition(
                active,
                PlacementIntentState.INDETERMINATE,
                reason_code="exchange_response_lost",
            )
            logging.warning(
                "Order requires reconciliation operation=%s symbol=%s side=%s failure=%s",
                active,
                symbol,
                side,
                type(exc).__name__,
            )
            if isinstance(exc, ExchangeSubmissionIndeterminate):
                raise
            raise ExchangeSubmissionIndeterminate(
                action=side,
                symbol=symbol,
                client_order_id=None,
                operation_id=operation_id,
            ) from exc
        identity = (
            result.get("id") or result.get("orderid")
            if isinstance(result, dict)
            else None
        )
        if require_acknowledgement and (not isinstance(identity, str) or not identity):
            await self.intents.transition(
                operation_id,
                PlacementIntentState.INDETERMINATE,
                reason_code="ack_missing_identity",
            )
            logging.warning(
                "Order requires reconciliation operation=%s symbol=%s side=%s failure=missing_acknowledgement_identity",
                operation_id,
                symbol,
                side,
            )
            raise ExchangeSubmissionIndeterminate(
                action=side,
                symbol=symbol,
                client_order_id=None,
                operation_id=operation_id,
            )
        if identity:
            active = result.get("_placement_operation_id") or operation_id
            await self.intents.transition(
                active,
                PlacementIntentState.ACCEPTED,
                exchange_order_id=str(identity),
                result=dict(result),
            )
            logging.info(
                "Order acknowledged operation=%s symbol=%s side=%s order_id=%s",
                active,
                symbol,
                side,
                identity,
            )
        return result

    @staticmethod
    def log_persisted(
        operation_id: str | None,
        *,
        symbol: str,
        side: str,
        order_id: str,
        amount: str,
        quote_cost: str,
    ) -> None:
        """Log allowlisted evidence only after the owning transaction commits."""
        logging.info(
            "Order fill persisted operation=%s exchange_order_id=%s symbol=%s side=%s amount=%s quote=%s",
            operation_id,
            order_id,
            symbol,
            side,
            amount,
            quote_cost,
        )
