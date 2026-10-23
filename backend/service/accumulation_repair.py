"""Explicit, lookup-only repair of restored accumulation order quarantine."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import model
from service.accumulation_accounting import persist_accumulation_order
from service.accumulation_commands import (
    CLOSE_ACTIONS,
    RETIRABLE_ACTIONS,
    AccumulationCommandResult,
    validate_operation_id,
)
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_fill import AccumulationFill
from service.accumulation_lifecycle import _require_settled
from service.accumulation_order_fees import hydrate_accumulation_order
from service.accumulation_ownership_evidence import (
    native_client_identity,
    recoverable_client_order_id,
)
from service.accumulation_state import AccumulationConflictError
from service.database import run_sqlite_write_with_retry
from service.exchange_capabilities import ExchangeOrderLookupStatus
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.order_requests import normalize_order_symbol
from tortoise.transactions import in_transaction


class AccumulationOrderRepair:
    """Journal intent before signed lookup; never submit, cancel, or unlock an order."""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    async def submit(self, payload: dict[str, Any]) -> AccumulationCommandResult:
        """Retry the same journal request explicitly until terminal evidence exists."""
        if isinstance(payload, dict) and payload.get("action") == "restore_inventory":
            from service.accumulation_inventory_restore import (
                AccumulationInventoryRestore,
            )

            return await AccumulationInventoryRestore(self.adapter).submit(payload)
        if (
            isinstance(payload, dict)
            and payload.get("action") == "acknowledge_settlement"
        ):
            from service.accumulation_settlement_ack import acknowledge_settlement

            return await acknowledge_settlement(payload)
        if isinstance(payload, dict) and payload.get("action") == "adjust_inventory":
            from service.accumulation_adjustment import AccumulationInventoryAdjustment

            return await AccumulationInventoryAdjustment(self.adapter).submit(payload)
        if isinstance(payload, dict) and payload.get("action") == "declare_ownership":
            from service.accumulation_ownership_declaration import (
                AccumulationOwnershipDeclaration,
            )

            return await AccumulationOwnershipDeclaration(self.adapter).submit(payload)
        if isinstance(payload, dict) and payload.get("action") == "retire_command":
            return await AccumulationCommandRetirement(self.adapter).submit(payload)
        if isinstance(payload, dict) and payload.get("action") == "rebind_account":
            from service.accumulation_account_rebind import AccumulationAccountRebind

            return await AccumulationAccountRebind(self.adapter).submit(payload)
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "symbol",
                "action",
                "operation_id",
                "expected_revision",
                "placement_operation_id",
            }
            or payload["action"] != "repair_order"
        ):
            raise AccumulationStateError("Invalid order-repair request.")
        if not isinstance(payload["symbol"], str):
            raise AccumulationStateError("Invalid repair symbol.")
        symbol = normalize_order_symbol(payload["symbol"])
        operation_id = validate_operation_id(payload["operation_id"])
        target = validate_operation_id(payload["placement_operation_id"])
        revision = payload["expected_revision"]
        if type(revision) is not int or not 0 <= revision < 2**63 - 1:
            raise AccumulationStateError("Invalid repair revision.")
        config = self.adapter.config()
        scope = await self.adapter.account_scope(config)
        request = json.dumps(
            {**payload, "symbol": symbol, "account_scope": scope}, sort_keys=True
        )

        async def journal() -> tuple[Any, Any]:
            async with in_transaction() as conn:
                prior = await model.AccumulationLifecycleOperation.get_or_none(
                    operation_id=operation_id
                ).using_db(conn)
                if prior is not None:
                    if prior.request_json != request:
                        raise AccumulationConflictError(
                            "Repair operation ID belongs to another request."
                        )
                    placement = await model.PlacementIntent.get(
                        operation_id=target
                    ).using_db(conn)
                    return prior, placement
                activation = await model.AccumulationActivation.get_or_none(
                    symbol=symbol
                ).using_db(conn)
                placement = await model.PlacementIntent.get_or_none(
                    operation_id=target
                ).using_db(conn)
                if (
                    activation is None
                    or activation.revision != revision
                    or not activation.explicitly_paused
                    or placement is None
                    or placement.symbol != symbol
                    or placement.exchange_name != config["exchange"].lower()
                    or placement.state not in {"quarantined", "restored_quarantined"}
                ):
                    raise AccumulationConflictError(
                        "Repair requires current paused ownership and a quarantined order."
                    )
                if not placement.exchange_order_id and not recoverable_client_order_id(
                    placement
                ):
                    raise AccumulationStateError(
                        "Order has no durable exchange lookup identity; manual investigation is required."
                    )
                if activation.account_scope != scope and not native_client_identity(
                    placement
                ):
                    raise AccumulationConflictError(
                        "Changed credentials require the original client order identity."
                    )
                attempt = await model.AccumulationAttempt.get_or_none(
                    placement=placement
                ).using_db(conn)
                sale = await model.AccumulationLifecycleOperation.get_or_none(
                    placement=placement
                ).using_db(conn)
                if (attempt is None) == (sale is None):
                    raise AccumulationStateError(
                        "Order requires exactly one accumulation owner."
                    )
                if attempt:
                    opportunity = await model.AccumulationOpportunity.get(
                        id=attempt.opportunity_id
                    ).using_db(conn)
                    if (
                        opportunity.activation_id != activation.id
                        or opportunity.generation != activation.generation
                    ):
                        raise AccumulationStateError(
                            "Order opportunity ownership changed."
                        )
                elif (
                    sale.activation_id != activation.id or sale.status != "quarantined"
                ):
                    raise AccumulationStateError(
                        "Sale command is not quarantined under this activation."
                    )
                activation.revision += 1
                await activation.save(using_db=conn)
                row = await model.AccumulationLifecycleOperation.create(
                    using_db=conn,
                    operation_id=operation_id,
                    activation=activation,
                    action="repair_order",
                    request_json=request,
                    status="quarantined",
                    previous_state=activation.state,
                    previous_paused=True,
                    result_state=activation.state,
                    result_revision=activation.revision,
                    reason="terminal_evidence_required",
                )
                return row, placement

        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                raise AccumulationConflictError("Trading maintenance is active.")
            row, placement = await run_sqlite_write_with_retry(
                journal, "journaling accumulation repair"
            )
        if row.status == "applied":
            return AccumulationCommandResult.from_operation(row)
        if row.status != "quarantined":
            raise AccumulationConflictError("This repair is no longer active.")
        # No symbol lock or database transaction is held over exchange I/O.
        async with asyncio.timeout(10):
            lookup = await self.adapter.exchange.lookup_spot_order(
                symbol,
                config,
                exchange_order_id=placement.exchange_order_id,
                client_order_id=recoverable_client_order_id(placement),
            )
        if lookup.status != ExchangeOrderLookupStatus.FOUND or lookup.order is None:
            return AccumulationCommandResult.from_operation(row)
        lookup_order = await hydrate_accumulation_order(
            self.adapter.exchange, lookup.order, config
        )
        report = AccumulationFill.from_order(lookup_order)
        if not report.terminal or not report.fees_complete:
            return AccumulationCommandResult.from_operation(row)
        if (
            self.adapter.config() != config
            or await self.adapter.account_scope(config) != scope
        ):
            raise AccumulationConflictError(
                "Account configuration changed during repair."
            )
        await persist_accumulation_order(
            target,
            lookup_order,
            account_scope=scope,
            exchange_name=config["exchange"].lower(),
            repair_operation_id=operation_id,
        )
        await row.refresh_from_db()
        return AccumulationCommandResult.from_operation(row)


class AccumulationCommandRetirement:
    """Retire an interrupted, unplaced intent without restoring its old automation."""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    async def submit(self, payload: dict[str, Any]) -> AccumulationCommandResult:
        """Atomically retire exactly the reviewed command and journal the decision."""
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "symbol",
                "action",
                "operation_id",
                "expected_revision",
                "previous_operation_id",
            }
            or payload["action"] != "retire_command"
        ):
            raise AccumulationStateError("Invalid command-retirement request.")
        if not isinstance(payload["symbol"], str):
            raise AccumulationStateError("Invalid retirement symbol.")
        symbol = normalize_order_symbol(payload["symbol"])
        operation_id = validate_operation_id(payload["operation_id"])
        previous_id = validate_operation_id(payload["previous_operation_id"])
        revision = payload["expected_revision"]
        if type(revision) is not int or not 0 <= revision < 2**63 - 1:
            raise AccumulationStateError("Invalid retirement revision.")
        config = self.adapter.config()
        scope = await self.adapter.account_scope(config)
        request = json.dumps(
            {**payload, "symbol": symbol, "account_scope": scope}, sort_keys=True
        )

        async def persist() -> AccumulationCommandResult:
            async with in_transaction() as conn:
                prior = await model.AccumulationLifecycleOperation.get_or_none(
                    operation_id=operation_id
                ).using_db(conn)
                if prior is not None:
                    if prior.request_json != request:
                        raise AccumulationConflictError(
                            "Operation ID belongs to a different retirement request."
                        )
                    return AccumulationCommandResult.from_operation(prior)
                activation = await model.AccumulationActivation.get_or_none(
                    symbol=symbol
                ).using_db(conn)
                previous = await model.AccumulationLifecycleOperation.get_or_none(
                    operation_id=previous_id
                ).using_db(conn)
                if (
                    activation is None
                    or activation.account_scope != scope
                    or activation.revision != revision
                    or not activation.explicitly_paused
                    or previous is None
                    or previous.activation_id != activation.id
                    or previous.status != "quarantined"
                    or previous.placement_id is not None
                    or previous.action not in RETIRABLE_ACTIONS
                ):
                    raise AccumulationConflictError(
                        "Retirement requires current paused ownership and an unplaced quarantined command."
                    )
                await _require_settled(activation, conn)
                if (
                    await model.AccumulationLifecycleOperation.filter(
                        activation=activation, status="pending"
                    )
                    .using_db(conn)
                    .exists()
                ):
                    raise AccumulationConflictError(
                        "Settle the current command before retiring old intent."
                    )
                if (
                    activation.holding_id is not None
                    and not await model.OpenTrades.filter(
                        id=activation.holding_id,
                        symbol=symbol,
                        lifecycle_mode="accumulation",
                    )
                    .using_db(conn)
                    .exists()
                ):
                    raise AccumulationConflictError(
                        "Holding ownership requires repair first."
                    )
                if (
                    await model.OpenTrades.filter(symbol=symbol)
                    .exclude(id=activation.holding_id or -1)
                    .using_db(conn)
                    .exists()
                ):
                    raise AccumulationConflictError(
                        "Unlinked inventory requires ownership repair first."
                    )
                previous_state = activation.state
                # Retiring a close never cancels its durable no-buy latch.
                if activation.state != "stopped" and previous.action in CLOSE_ACTIONS:
                    activation.state = "closing"
                elif activation.state not in {"closing", "stopped"}:
                    activation.state = "paused"
                await (
                    model.AccumulationLifecycleOperation.filter(
                        activation=activation,
                        status="cancelled",
                        action__in=CLOSE_ACTIONS,
                        reason="restore_intent_retired",
                        result_revision=activation.revision,
                    )
                    .using_db(conn)
                    .update(result_revision=activation.revision + 1)
                )
                activation.revision += 1
                activation.reason = "restore_intent_retired_paused"
                await activation.save(using_db=conn)
                previous.status = "cancelled"
                previous.reason = "restore_intent_retired"
                previous.result_state = activation.state
                previous.result_revision = activation.revision
                await previous.save(using_db=conn)
                receipt = await model.AccumulationLifecycleOperation.create(
                    using_db=conn,
                    operation_id=operation_id,
                    activation=activation,
                    action="retire_command",
                    request_json=request,
                    status="applied",
                    previous_state=previous_state,
                    previous_paused=True,
                    result_state=activation.state,
                    result_revision=activation.revision,
                    reason="unplaced_intent_retired",
                )
                return AccumulationCommandResult.from_operation(receipt)

        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                raise AccumulationConflictError("Trading maintenance is active.")
            return await run_sqlite_write_with_retry(
                persist, "retiring restored accumulation intent"
            )
