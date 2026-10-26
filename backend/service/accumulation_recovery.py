"""Recover accumulation evidence without DCA finalizers or order resubmission."""

from collections.abc import Awaitable, Callable
from typing import Any

import model
from service.accumulation_accounting import (
    persist_accumulation_order,
    reject_unsubmitted_accumulation_order,
)
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_order_fees import hydrate_accumulation_order
from service.exchange_capabilities import ExchangeOrderLookupStatus
from service.placement_intents import (
    PlacementIntentService,
    PlacementIntentState,
    deserialize_placement_payload,
)

AccountScopeProvider = Callable[[dict[str, Any]], Awaitable[str]]


class AccumulationPlacementRecovery:
    """Require a trusted current-account identity provider before any lookup.

    Runtime wiring supplies that provider after ownership validation is added.
    A dashboard-supplied account label is not an acceptable provider.
    """

    def __init__(
        self,
        exchange: Any,
        account_scope: AccountScopeProvider,
        intents: PlacementIntentService | None = None,
    ) -> None:
        self.exchange = exchange
        self.account_scope = account_scope
        self.intents = intents or PlacementIntentService()

    async def reconcile(self, intent: Any, config: dict[str, Any]) -> str:
        """Account partial/terminal evidence and keep unknown placements committed."""
        if intent.state in {"quarantined", "restored_quarantined"}:
            return str(intent.state)
        scope = await self.account_scope(config)
        activation = await model.AccumulationActivation.get_or_none(
            symbol=intent.symbol
        )
        exchange_name = str(config.get("exchange") or "").lower()
        if (
            activation is None
            or activation.account_scope != scope
            or exchange_name != intent.exchange_name
            or config.get("market") != "spot"
        ):
            raise AccumulationStateError(
                "Accumulation recovery account is not validated."
            )
        if intent.state == "persisted":
            checkpoint = await model.AccumulationFillCheckpoint.get_or_none(
                placement_id=intent.id
            )
            if (
                checkpoint is None
                or not checkpoint.terminal
                or not checkpoint.fees_complete
            ):
                raise AccumulationStateError(
                    "Persisted accumulation fill has no complete checkpoint."
                )
            await self.intents.transition(
                intent.operation_id, PlacementIntentState.COMPLETED
            )
            return "completed"
        if intent.state == "prepared":
            return await reject_unsubmitted_accumulation_order(
                intent.operation_id, account_scope=scope, exchange_name=exchange_name
            )
        if intent.state == "filled":
            evidence = deserialize_placement_payload(intent.result_json)
        else:
            lookup = await self.exchange.lookup_spot_order(
                intent.symbol,
                config,
                exchange_order_id=intent.exchange_order_id,
                client_order_id=intent.client_order_id,
            )
            if lookup.status != ExchangeOrderLookupStatus.FOUND or lookup.order is None:
                # A failed lookup is not proof of zero fill or safe resubmission.
                return str(intent.state)
            evidence = lookup.order
        evidence = await hydrate_accumulation_order(self.exchange, evidence, config)
        result = await persist_accumulation_order(
            intent.operation_id,
            evidence,
            account_scope=scope,
            exchange_name=exchange_name,
        )
        if result.settled:
            await self.intents.transition(
                intent.operation_id, PlacementIntentState.COMPLETED
            )
            return "completed"
        return "accepted"
