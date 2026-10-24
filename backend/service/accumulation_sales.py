"""Execute journaled accumulation commands and archive verified full-close dust.

One sale command owns one placement. A sellable terminal remainder requires an
explicit retry; unsellable dust is preserved in the existing archive automatically.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import ccxt.async_support as ccxt
import model
from service.accumulation_accounting import persist_accumulation_order
from service.accumulation_commands import CLOSE_ACTIONS, ENTRY_ACTIONS, SALE_ACTIONS
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_exchange import (
    AccumulationExchangeAdapter,
    AccumulationSaleInputs,
    AccumulationSaleSizeError,
)
from service.accumulation_execution import AccumulationExecutionResult
from service.accumulation_lifecycle import (
    AccumulationLifecycleService,
    _require_sale_checkpoint,
    _require_settled,
)
from service.accumulation_recovery import AccumulationPlacementRecovery
from service.accumulation_state import AccumulationConflictError
from service.database import run_sqlite_write_with_retry
from service.exchange_capabilities import (
    ExchangeSubmissionIndeterminate,
    build_client_order_id,
)
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.placement_intents import PlacementIntentService, PlacementIntentState
from service.placement_workflow import PlacementWorkflow
from service.trading_maintenance import trading_maintenance_barrier
from tortoise.transactions import in_transaction


class AccumulationCommandExecutor:
    """Settle owned buys, then execute only an already journaled manual intent."""

    def __init__(self, adapter: AccumulationExchangeAdapter) -> None:
        self.adapter = adapter
        self.intents = PlacementIntentService()
        self.recovery = AccumulationPlacementRecovery(
            adapter.exchange, adapter.account_scope
        )
        self.lifecycle = AccumulationLifecycleService(adapter.readiness)

    async def _command(
        self, operation_id: str, scope: str
    ) -> tuple[model.AccumulationLifecycleOperation, model.AccumulationActivation]:
        operation = await model.AccumulationLifecycleOperation.get_or_none(
            operation_id=operation_id
        )
        if operation is None:
            raise AccumulationStateError("A persisted operator command is required.")
        activation = await model.AccumulationActivation.get(id=operation.activation_id)
        if activation.account_scope != scope:
            raise AccumulationStateError("Operator command belongs to another account.")
        if (
            operation.status == "pending"
            and operation.result_revision != activation.revision
        ):
            raise AccumulationConflictError("Operator command is no longer current.")
        return operation, activation

    async def _settle_buys(self, operation_id: str, config: dict[str, Any]) -> None:
        scope = await self.adapter.account_scope(config)
        operation, activation = await self._command(operation_id, scope)
        pending = await model.PlacementIntent.filter(
            symbol=activation.symbol, side="buy"
        ).exclude(state__in=["completed", "rejected"])
        for row in pending:
            attempt = await model.AccumulationAttempt.get_or_none(placement_id=row.id)
            if attempt is None:
                raise AccumulationStateError("Unowned order requires explicit repair.")
            opportunity = await model.AccumulationOpportunity.get(
                id=attempt.opportunity_id
            )
            if opportunity.activation_id != activation.id:
                raise AccumulationStateError("Buy ownership changed.")
            # Lookup and accounting happen outside the public symbol boundary.
            # Prepared orders are rejected only with proof they were never sent.
            async with asyncio.timeout(10):
                await self.recovery.reconcile(row, config)
            async with lifecycle_mutation_coordinator.mutation(row.symbol) as admitted:
                if not admitted:
                    raise AccumulationConflictError("Maintenance is active.")
                operation, activation = await self._command(operation_id, scope)
                if operation.status != "pending":
                    return
                await row.refresh_from_db()
                checkpoint = await model.AccumulationFillCheckpoint.get_or_none(
                    placement_id=row.id
                )
                if row.state in {"completed", "rejected"}:
                    continue
                if (
                    checkpoint is None
                    or checkpoint.terminal
                    or not row.exchange_order_id
                ):
                    continue
                await self.adapter.account_scope(config)
                # Persist cancellation intent on its owned order before I/O. A
                # repeated cancel targets the same confirmed order, never a new
                # placement. Its response alone cannot release the commitment.
                row.reason_code = "accumulation_cancel_requested"
                await row.save(update_fields=["reason_code", "updated_at"])
                async with asyncio.timeout(10):
                    await self.adapter.exchange.cancel_spot_order(
                        row.symbol, row.exchange_order_id, config
                    )
            async with asyncio.timeout(10):
                await self.recovery.reconcile(
                    await self.intents.get(row.operation_id), config
                )

    async def _claim_sale(
        self,
        operation_id: str,
        config: dict[str, Any],
        quantity: str,
        revision: int,
        inputs: AccumulationSaleInputs,
    ) -> model.PlacementIntent | None:
        async def persist() -> model.PlacementIntent | None:
            async with in_transaction() as connection:
                scope = await self.adapter.account_scope(config)
                operation, activation = await self.lifecycle._load_completion(
                    operation_id, scope, connection
                )
                if operation.placement_id is not None:
                    return None
                expected_state = {
                    "close": "closing",
                    "retry_close": "closing",
                    "sell_partial": "selling_partial",
                }.get(operation.action)
                if (
                    operation.status != "pending"
                    or activation.state != expected_state
                    or activation.revision != revision
                    or self.adapter.config() != config
                    or not 0 <= self.adapter.clock_ms() - inputs.observed_at_ms <= 10000
                ):
                    raise AccumulationConflictError(
                        "Sale preflight is no longer current."
                    )
                await _require_settled(activation, connection)
                holding = await model.OpenTrades.get_or_none(
                    id=activation.holding_id
                ).using_db(connection)
                if (
                    holding is None
                    or holding.symbol != activation.symbol
                    or holding.lifecycle_mode != "accumulation"
                ):
                    raise AccumulationStateError(
                        "Owned accumulation holding is required."
                    )
                net = Decimal(
                    canonical_decimal(holding.accumulation_net_quantity, positive=True)
                )
                requested = Decimal(canonical_decimal(quantity, positive=True))
                amount = Decimal(canonical_decimal(inputs.amount, positive=True))
                if (
                    amount > requested
                    or requested > net
                    or (
                        operation.action == "sell_partial"
                        and (
                            requested >= net or quantity != operation.requested_quantity
                        )
                    )
                    or (operation.action in CLOSE_ACTIONS and requested != net)
                ):
                    raise AccumulationStateError(
                        "Sale exceeds the authorized owned quantity."
                    )
                placement_id = f"sell-{uuid4().hex}"
                source_operation_id = None
                if operation.action == "retry_close":
                    previous = await model.AccumulationLifecycleOperation.get(
                        operation_id=json.loads(operation.request_json)[
                            "previous_operation_id"
                        ],
                        activation_id=activation.id,
                    ).using_db(connection)
                    if previous.placement_id is None:
                        if (
                            previous.status != "continued"
                            or previous.reason != "explicit_close_retry"
                            or previous.action not in CLOSE_ACTIONS
                        ):
                            raise AccumulationConflictError(
                                "The unplaced predecessor was not explicitly continued."
                            )
                    else:
                        await _require_sale_checkpoint(previous, activation, connection)
                    if previous.placement_id is not None:
                        source = await model.PlacementIntent.get(
                            id=previous.placement_id
                        ).using_db(connection)
                        source_operation_id = source.operation_id
                row = await model.PlacementIntent.create(
                    using_db=connection,
                    operation_id=placement_id,
                    source_operation_id=source_operation_id,
                    client_order_id=build_client_order_id(placement_id),
                    exchange_name=config["exchange"],
                    symbol=activation.symbol,
                    action="sell",
                    side="sell",
                    order_type="market",
                    state="submitting",
                    requested_amount=float(amount),
                    submitted_at=datetime.fromtimestamp(
                        self.adapter.clock_ms() / 1000, timezone.utc
                    ),
                    request_json=json.dumps(
                        {
                            "symbol": activation.symbol,
                            "_execution_scope": activation.account_scope,
                            "amount": inputs.amount,
                            "accumulation_operation_id": operation_id,
                            "accumulation_action": operation.action,
                            "authorized_quantity": quantity,
                            "holding_id": holding.id,
                            "generation": str(activation.generation),
                        },
                        sort_keys=True,
                    ),
                )
                operation.placement_id = row.id
                await operation.save(using_db=connection)
                return row

        return await run_sqlite_write_with_retry(
            persist, "claiming manual accumulation sale"
        )

    async def _archive_remainder(
        self, operation_id: str
    ) -> AccumulationExecutionResult | None:
        """Try the shared archive path only for a current full-close command."""
        from service.accumulation_dust import archive_accumulation_dust

        scope = await self.adapter.account_scope(self.adapter.config())
        operation, activation = await self._command(operation_id, scope)
        if operation.status != "pending" or operation.action not in CLOSE_ACTIONS:
            return None
        try:
            result = await archive_accumulation_dust(
                {
                    "symbol": activation.symbol,
                    "action": "archive_dust",
                    "operation_id": f"dust-{uuid5(NAMESPACE_URL, operation_id).hex}",
                    "expected_revision": activation.revision,
                    "previous_operation_id": operation_id,
                },
                self.adapter,
            )
        except AccumulationStateError:
            # Sellable inventory, incomplete evidence or a concurrent revision
            # must retain the close latch, never weaken archive validation.
            return None
        return AccumulationExecutionResult(operation_id, result.status, "DUST_ARCHIVED")

    async def _finish(
        self, operation_id: str, scope: str, row: model.PlacementIntent
    ) -> AccumulationExecutionResult:
        try:
            await self.lifecycle.complete_settlement(operation_id, account_scope=scope)
        except AccumulationConflictError:
            archived = await self._archive_remainder(operation_id)
            if archived is not None:
                return archived
            return AccumulationExecutionResult(
                row.operation_id, str(row.state), "WAIT_REMAINDER"
            )
        return AccumulationExecutionResult(row.operation_id, str(row.state), "SETTLED")

    async def execute(self, operation_id: str) -> AccumulationExecutionResult:
        """Advance one durable operator command without generating replacement sales."""
        async with trading_maintenance_barrier.operation() as admitted:
            if not admitted:
                return AccumulationExecutionResult(
                    operation_id, "pending", "WAIT_MAINTENANCE"
                )
            try:
                return await self._execute(operation_id)
            except AccumulationSaleSizeError as exc:
                return AccumulationExecutionResult(operation_id, "pending", exc.reason)
            except (ccxt.BaseError, TimeoutError, OSError):
                return AccumulationExecutionResult(
                    operation_id, "pending", "WAIT_RECONCILIATION"
                )

    async def _execute(self, operation_id: str) -> AccumulationExecutionResult:
        config = self.adapter.config()
        scope = await self.adapter.account_scope(config)
        operation, activation = await self._command(operation_id, scope)
        if operation.status != "pending":
            return AccumulationExecutionResult(
                operation_id,
                operation.status,
                "ALREADY_APPLIED" if operation.status == "applied" else "INACTIVE",
            )
        if operation.action in ENTRY_ACTIONS:
            return AccumulationExecutionResult(
                operation_id, "pending", "WAIT_ENTRY_VALIDATION"
            )
        if operation.action not in {
            "close",
            "retry_close",
            "sell_partial",
            "pause",
            "switch_strategy",
            "resume",
            "reactivate",
            "activate",
        }:
            raise AccumulationStateError("Unsupported operator command.")
        await self._settle_buys(operation_id, config)
        operation, activation = await self._command(operation_id, scope)
        if operation.action not in SALE_ACTIONS:
            if operation.action == "pause":
                result = await self.lifecycle.complete_settlement(
                    operation_id, account_scope=scope
                )
            else:
                result = await self.lifecycle.complete_rebase(
                    operation_id, account_scope=scope
                )
            return AccumulationExecutionResult(operation_id, result.status, "SETTLED")
        if operation.placement_id is not None:
            row = await model.PlacementIntent.get(id=operation.placement_id)
            if row.state not in {"completed", "rejected"}:
                async with asyncio.timeout(10):
                    await self.recovery.reconcile(row, config)
                await row.refresh_from_db()
            if row.state == "completed":
                return await self._finish(operation_id, scope, row)
            return AccumulationExecutionResult(
                row.operation_id, str(row.state), "WAIT_RECONCILIATION"
            )
        async with in_transaction() as connection:
            await _require_settled(activation, connection)
            holding = await model.OpenTrades.get_or_none(
                id=activation.holding_id
            ).using_db(connection)
            if holding is None:
                raise AccumulationStateError(
                    "Owned inventory is required for a manual sale."
                )
            quantity = canonical_decimal(
                operation.requested_quantity
                if operation.action == "sell_partial"
                else holding.accumulation_net_quantity,
                positive=True,
            )
        try:
            inputs = await self.adapter.sale_inputs(activation.symbol, quantity, config)
        except AccumulationSaleSizeError as exc:
            if exc.reason in {"WAIT_PRECISION", "WAIT_MINIMUM"}:
                archived = await self._archive_remainder(operation_id)
                if archived is not None:
                    return archived
            raise
        async with lifecycle_mutation_coordinator.mutation(
            activation.symbol
        ) as admitted:
            if not admitted:
                return AccumulationExecutionResult(
                    operation_id, "pending", "WAIT_MAINTENANCE"
                )
            row = await self._claim_sale(
                operation_id, config, quantity, activation.revision, inputs
            )
            if row is None:
                return AccumulationExecutionResult(
                    operation_id, "pending", "ALREADY_CLAIMED"
                )

            async def submit_sell() -> dict[str, Any]:
                async with asyncio.timeout(10):
                    return await self.adapter.exchange.submit_preflighted_spot_sell(
                        symbol=row.symbol,
                        amount=inputs.amount,
                        client_order_id=row.client_order_id,
                        config=config,
                    )

            try:
                evidence = await PlacementWorkflow(self.intents).submit(
                    row.operation_id,
                    symbol=row.symbol,
                    side="sell",
                    submit=submit_sell,
                    require_acknowledgement=True,
                )
            except ExchangeSubmissionIndeterminate:
                return AccumulationExecutionResult(
                    row.operation_id, "indeterminate", "WAIT_RECONCILIATION"
                )
        try:
            result = await persist_accumulation_order(
                row.operation_id,
                evidence,
                account_scope=scope,
                exchange_name=config["exchange"],
            )
        except AccumulationStateError:
            return AccumulationExecutionResult(
                row.operation_id, "accepted", "WAIT_RECONCILIATION"
            )
        if not result.settled:
            return AccumulationExecutionResult(
                row.operation_id, "accepted", "WAIT_RECONCILIATION"
            )
        await self.intents.transition(row.operation_id, PlacementIntentState.COMPLETED)
        await row.refresh_from_db()
        return await self._finish(operation_id, scope, row)
