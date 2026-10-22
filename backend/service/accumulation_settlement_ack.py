"""Acknowledge an interrupted command using already committed settlement evidence."""

import json
from typing import Any

import model
from service.accumulation_accounting import _inventory
from service.accumulation_commands import (
    CLOSE_ACTIONS,
    SALE_ACTIONS,
    validate_operation_id,
)
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_lifecycle import _require_settled, _result
from service.accumulation_state import AccumulationConflictError
from service.database import run_sqlite_write_with_retry
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.order_requests import normalize_order_symbol
from tortoise.transactions import in_transaction


async def acknowledge_settlement(payload: dict[str, Any]) -> Any:
    """Record acknowledgement without accessing an exchange or changing inventory."""
    if (
        set(payload)
        != {
            "symbol",
            "action",
            "operation_id",
            "expected_revision",
            "previous_operation_id",
        }
        or payload.get("action") != "acknowledge_settlement"
    ):
        raise AccumulationStateError("Invalid settlement acknowledgement.")
    if not isinstance(payload["symbol"], str):
        raise AccumulationStateError("Invalid acknowledgement symbol.")
    symbol = normalize_order_symbol(payload["symbol"])
    operation_id = validate_operation_id(payload["operation_id"])
    target = validate_operation_id(payload["previous_operation_id"])
    revision = payload["expected_revision"]
    if type(revision) is not int or not 0 <= revision < 2**63 - 1:
        raise AccumulationStateError("Invalid acknowledgement revision.")
    request = json.dumps({**payload, "symbol": symbol}, sort_keys=True)

    async def persist() -> Any:
        async with in_transaction() as conn:
            prior = await model.AccumulationLifecycleOperation.get_or_none(
                operation_id=operation_id
            ).using_db(conn)
            if prior is not None:
                if prior.request_json != request:
                    raise AccumulationConflictError(
                        "Operation ID belongs to another request."
                    )
                return _result(prior)
            activation = await model.AccumulationActivation.get_or_none(
                symbol=symbol
            ).using_db(conn)
            command = await model.AccumulationLifecycleOperation.get_or_none(
                operation_id=target
            ).using_db(conn)
            if (
                activation is None
                or activation.revision != revision
                or not activation.explicitly_paused
                or command is None
                or command.activation_id != activation.id
                or command.status != "quarantined"
                or command.action not in SALE_ACTIONS
                or command.placement_id is None
            ):
                raise AccumulationConflictError(
                    "Select a settled quarantined sale under the current paused registration."
                )
            await _require_settled(activation, conn)
            placement = await model.PlacementIntent.get(
                id=command.placement_id
            ).using_db(conn)
            checkpoint = await model.AccumulationFillCheckpoint.get_or_none(
                placement=placement
            ).using_db(conn)
            latest = (
                await model.AccumulationFillCheckpoint.filter(activation=activation)
                .using_db(conn)
                .order_by("-updated_at", "-id")
                .first()
            )
            holding = (
                await model.OpenTrades.get_or_none(id=activation.holding_id).using_db(
                    conn
                )
                if activation.holding_id
                else None
            )
            if (
                placement.state != "completed"
                or placement.symbol != symbol
                or placement.side != "sell"
                or checkpoint is None
                or checkpoint.activation_id != activation.id
                or not checkpoint.terminal
                or not checkpoint.fees_complete
                or latest is None
                or latest.id != checkpoint.id
                or holding is not None
                and (
                    holding.symbol != symbol or holding.lifecycle_mode != "accumulation"
                )
                or await model.OpenTrades.filter(symbol=symbol)
                .exclude(id=activation.holding_id or -1)
                .using_db(conn)
                .exists()
            ):
                raise AccumulationConflictError(
                    "Complete, current settlement and inventory evidence is required."
                )
            inventory = _inventory(holding)
            try:
                recorded = json.loads(checkpoint.inventory_json or "null")
                if not isinstance(recorded, dict) or (
                    holding is not None
                    and recorded != json.loads(inventory.serialize())
                    or holding is None
                    and (
                        canonical_decimal(recorded["quantity"]) != "0"
                        or canonical_decimal(recorded["remaining_cost"]) != "0"
                        or recorded["pending_fee_reports"] != 0
                    )
                ):
                    raise ValueError("Inventory differs from settlement")
            except (ValueError, TypeError, KeyError):
                raise AccumulationConflictError(
                    "Restore the exact settled inventory before acknowledgement."
                ) from None
            previous_state = activation.state
            if command.action in CLOSE_ACTIONS:
                activation.state = "stopped" if inventory.quantity == "0" else "closing"
                command.status = (
                    "applied" if inventory.quantity == "0" else "reconciled"
                )
            else:
                if inventory.quantity == "0":
                    raise AccumulationConflictError(
                        "A partial sale cannot silently close a registration."
                    )
                activation.state = (
                    "closing" if activation.state == "closing" else "paused"
                )
                command.status = "applied"
            activation.revision += 1
            activation.reason = "settlement_acknowledged_paused"
            await activation.save(using_db=conn)
            command.result_state = activation.state
            command.result_revision = activation.revision
            command.reason = "settlement_acknowledged"
            await command.save(using_db=conn)
            receipt = await model.AccumulationLifecycleOperation.create(
                using_db=conn,
                activation=activation,
                operation_id=operation_id,
                action="acknowledge_settlement",
                request_json=request,
                status="applied",
                previous_state=previous_state,
                previous_paused=True,
                result_state=activation.state,
                result_revision=activation.revision,
                reason="settlement_acknowledged",
            )
            return _result(receipt)

    async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
        if not admitted:
            raise AccumulationConflictError("Trading maintenance is active.")
        return await run_sqlite_write_with_retry(
            persist, "acknowledging settled accumulation command"
        )
