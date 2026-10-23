"""Verified, atomic transfer of an unsellable remainder out of active management."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import model
from service.accumulation_accounting import _inventory
from service.accumulation_commands import (
    CLOSE_ACTIONS,
    AccumulationAction,
    AccumulationCommand,
    AccumulationCommandResult,
)
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_exchange import (
    AccumulationExchangeAdapter,
    AccumulationSaleSizeError,
)
from service.accumulation_lifecycle import _require_sale_checkpoint, _require_settled
from service.accumulation_state import AccumulationConflictError
from service.database import run_sqlite_write_with_retry
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from tortoise.transactions import in_transaction


def _result(operation: Any) -> AccumulationCommandResult:
    return AccumulationCommandResult(
        operation.operation_id,
        str(operation.activation_id),
        operation.status,
        operation.result_state,
        operation.result_revision,
        operation.reason,
    )


async def _retry(command: AccumulationCommand, request: str, connection: Any) -> Any:
    prior = await model.AccumulationLifecycleOperation.get_or_none(
        operation_id=command.operation_id
    ).using_db(connection)
    if prior is None:
        return None
    body = json.loads(prior.request_json)
    if not isinstance(body, dict):
        raise AccumulationConflictError("Operation ID already exists.")
    body.pop("_archive", None)
    if prior.action != "archive_dust" or body != json.loads(request):
        raise AccumulationConflictError(
            "Operation ID was already used for another request."
        )
    return _result(prior)


async def _require_close_accounting(
    close: Any, activation: Any, connection: Any
) -> None:
    """Follow unplaced retries to their settled sale without inventing an order."""
    seen = set()
    while close.placement_id is None:
        if close.operation_id in seen or len(seen) >= 1000:
            raise AccumulationConflictError("Invalid close retry chain.")
        seen.add(close.operation_id)
        if close.action == "close":
            # Placement creation and attachment are atomic. This initial close
            # never sent an order; _require_settled still checks all obligations.
            return
        try:
            predecessor = json.loads(close.request_json)["previous_operation_id"]
        except (ValueError, TypeError, KeyError) as exc:
            raise AccumulationConflictError("Invalid close retry chain.") from exc
        close = await model.AccumulationLifecycleOperation.get_or_none(
            operation_id=predecessor, activation_id=activation.id
        ).using_db(connection)
        if (
            close is None
            or close.action not in CLOSE_ACTIONS
            or close.status != "continued"
            or close.reason != "explicit_close_retry"
        ):
            raise AccumulationConflictError("A settled close predecessor is required.")
    await _require_sale_checkpoint(close, activation, connection)


async def _snapshot(
    command: AccumulationCommand, scope: str, connection: Any
) -> tuple[Any, Any, Any, str]:
    activation = await model.AccumulationActivation.get_or_none(
        symbol=command.symbol
    ).using_db(connection)
    if activation is None or activation.account_scope != scope:
        raise AccumulationConflictError(
            "Registration account changed; refresh before archiving."
        )
    if (
        activation.state != "closing"
        or activation.revision != command.expected_revision
    ):
        raise AccumulationConflictError(
            "Archive requires the current Closing revision."
        )
    pending = await model.AccumulationLifecycleOperation.filter(
        activation=activation,
        status__in=["pending", "reconciled", "quarantined"],
    ).using_db(connection)
    if (
        len(pending) != 1
        or pending[0].status == "quarantined"
        or pending[0].action not in CLOSE_ACTIONS
        or pending[0].operation_id != command.previous_operation_id
        or pending[0].result_revision != activation.revision
    ):
        raise AccumulationConflictError(
            "Archive must reference the current settled close."
        )
    close = pending[0]
    await _require_settled(activation, connection)
    await _require_close_accounting(close, activation, connection)
    holding = await model.OpenTrades.get_or_none(id=activation.holding_id).using_db(
        connection
    )
    if (
        holding is None
        or holding.symbol != command.symbol
        or holding.lifecycle_mode != "accumulation"
        or not holding.deal_id
        or not holding.execution_history_complete
    ):
        raise AccumulationConflictError("A verified accumulation holding is required.")
    inventory = _inventory(holding)
    if Decimal(inventory.quantity) <= 0 or inventory.pending_fee_reports != 0:
        raise AccumulationConflictError(
            "Positive inventory and complete fees are required."
        )
    snapshot = json.dumps(
        {
            "schema_version": 1,
            "activation_id": str(activation.id),
            "generation": str(activation.generation),
            "account_scope": scope,
            "symbol": command.symbol,
            "deal_id": holding.deal_id,
            "inventory": asdict(inventory),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return activation, holding, close, snapshot


async def archive_accumulation_dust(
    payload: dict[str, Any], adapter: AccumulationExchangeAdapter
) -> AccumulationCommandResult:
    """Archive only a proved unsellable remainder; never trade or invent proceeds.

    Exchange I/O precedes the symbol lock. The atomic commit rechecks the exact
    inventory, command revision, account, settlement and freshness. A lost HTTP
    response can retry the original ID without repeating the transfer.
    """
    command = AccumulationCommand.from_dict(payload)
    if command.action != AccumulationAction.ARCHIVE_DUST:
        raise AccumulationStateError("Expected archive_dust.")
    config = adapter.config()
    scope = await adapter.account_scope(config)
    request = command.request_json(scope)
    async with in_transaction() as connection:
        prior = await _retry(command, request, connection)
        if prior is not None:
            return prior
        _, holding, _, snapshot = await _snapshot(command, scope, connection)
        quantity = holding.accumulation_net_quantity
    started = adapter.clock_ms()
    try:
        await adapter.sale_inputs(command.symbol, quantity, config)
    except AccumulationSaleSizeError as exc:
        if exc.reason not in {"WAIT_PRECISION", "WAIT_MINIMUM"}:
            raise AccumulationConflictError(
                "This size restriction is not proof of dust."
            ) from exc
        restriction = exc.reason
    else:
        raise AccumulationConflictError(
            "The remainder is sellable; use Retry remaining sale."
        )
    await adapter.account_scope(config)

    async def persist() -> AccumulationCommandResult:
        async with in_transaction() as connection:
            prior = await _retry(command, request, connection)
            if prior is not None:
                return prior
            activation, holding, close, current = await _snapshot(
                command, scope, connection
            )
            if current != snapshot or not 0 <= adapter.clock_ms() - started <= 10000:
                raise AccumulationConflictError(
                    "Inventory or exchange evidence changed; refresh and review again."
                )
            archive = json.loads(snapshot)
            archive["restriction"] = restriction
            archive["operation_id"] = command.operation_id
            archive["archived_at"] = datetime.now(timezone.utc).isoformat()
            inventory = archive["inventory"]
            await model.UnsellableTrades.create(
                using_db=connection,
                symbol=holding.symbol,
                deal_id=holding.deal_id,
                execution_history_complete=holding.execution_history_complete,
                amount=float(inventory["quantity"]),
                cost=float(inventory["remaining_cost"] or 0),
                so_count=holding.so_count,
                avg_price=holding.avg_price,
                current_price=holding.current_price,
                open_date=holding.open_date,
                unsellable_reason="Accumulation dust archived (unsold)",
                unsellable_since=archive["archived_at"],
                accumulation_inventory_json=json.dumps(archive, sort_keys=True),
            )
            previous_paused = activation.explicitly_paused
            activation.holding_id = None
            activation.state, activation.explicitly_paused = "stopped", True
            activation.revision += 1
            activation.reason = "dust_archived"
            await activation.save(using_db=connection)
            await holding.delete(using_db=connection)
            # A transfer to unmanaged inventory is not a sale or realized loss.
            # Preserve realized totals, but never report returns as if dust vanished.
            await (
                model.AccumulationReturnTotals.filter(activation=activation)
                .using_db(connection)
                .update(
                    last_quantity="0",
                    last_cost="0",
                    provenance_complete=False,
                )
            )
            close.status, close.reason = "applied", "remainder_archived"
            close.result_state, close.result_revision = "stopped", activation.revision
            await close.save(using_db=connection)
            operation = await model.AccumulationLifecycleOperation.create(
                using_db=connection,
                operation_id=command.operation_id,
                activation=activation,
                action="archive_dust",
                request_json=json.dumps(
                    {**json.loads(request), "_archive": archive}, sort_keys=True
                ),
                status="applied",
                previous_state="closing",
                previous_paused=previous_paused,
                result_state="stopped",
                result_revision=activation.revision,
                reason="dust_archived",
            )
            return _result(operation)

    async with lifecycle_mutation_coordinator.mutation(command.symbol) as admitted:
        if not admitted:
            raise AccumulationConflictError("Maintenance is active.")
        await adapter.account_scope(config)
        return await run_sqlite_write_with_retry(persist, "archiving accumulation dust")
