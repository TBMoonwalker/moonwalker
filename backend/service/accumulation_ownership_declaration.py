"""Explicit operator ownership declarations, never inferred account identity."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any

import model
from service.accumulation_account_rebind import AccumulationAccountRebind
from service.accumulation_accounting import _inventory
from service.accumulation_commands import (
    ENTRY_ACTIONS,
    RETIRABLE_ACTIONS,
    AccumulationCommandResult,
    validate_operation_id,
)
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_lifecycle import _require_settled
from service.accumulation_ownership_evidence import declared_unknown_fee_count
from service.accumulation_state import AccumulationConflictError
from service.database import run_sqlite_write_with_retry
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.order_requests import normalize_order_symbol
from tortoise.transactions import in_transaction


async def _plan(
    activation: Any, conn: Any, *, exclude_operation_id: str | None = None
) -> dict[str, Any]:
    await _require_settled(activation, conn)
    if activation.state not in {
        "enabled",
        "paused",
        "blocked",
        "validating",
        "closing",
        "stopped",
    }:
        raise AccumulationConflictError(
            "Settle the current lifecycle transition first."
        )
    holding = await model.OpenTrades.get_or_none(symbol=activation.symbol).using_db(
        conn
    )
    if (
        (holding is None) != (activation.holding_id is None)
        or holding is not None
        and (
            holding.id != activation.holding_id
            or holding.lifecycle_mode != "accumulation"
        )
    ):
        raise AccumulationConflictError(
            "Restore the recorded inventory link before declaring ownership."
        )
    if (
        await model.OpenTrades.filter(
            symbol__startswith=activation.symbol.split("/")[0] + "/"
        )
        .exclude(symbol=activation.symbol)
        .using_db(conn)
        .exists()
    ):
        raise AccumulationConflictError("Shared base-asset ownership is ambiguous.")
    if (
        await model.AccumulationFillCheckpoint.filter(
            activation=activation, fees_complete=False
        )
        .using_db(conn)
        .exists()
        or await model.AccumulationFillCheckpoint.filter(
            activation=activation, terminal=False
        )
        .using_db(conn)
        .exists()
    ):
        raise AccumulationConflictError("Complete native order and fee evidence first.")
    inv = _inventory(holding)
    if (
        holding is not None
        and inv.pending_fee_reports
        and (
            holding.execution_history_complete
            or inv.pending_fee_reports
            != await declared_unknown_fee_count(activation, conn)
        )
    ):
        raise AccumulationConflictError(
            "Unexplained execution fees require reconciliation."
        )
    if holding is None:
        totals = await model.AccumulationReturnTotals.get_or_none(
            activation=activation
        ).using_db(conn)
        latest = (
            await model.AccumulationFillCheckpoint.filter(activation=activation)
            .using_db(conn)
            .order_by("-updated_at", "-id")
            .first()
        )
        try:
            missing_inventory = (
                totals is not None
                and Decimal(canonical_decimal(totals.last_quantity)) != 0
                or latest is not None
                and latest.inventory_json
                and Decimal(
                    canonical_decimal(json.loads(latest.inventory_json)["quantity"])
                )
                != 0
            )
        except (ValueError, TypeError, KeyError):
            raise AccumulationConflictError(
                "Inventory evidence is corrupt; restore a complete backup."
            ) from None
        if missing_inventory:
            raise AccumulationConflictError(
                "Recorded inventory is missing; restore it before declaring ownership."
            )
    if not activation.observations_initialized and (
        holding is not None
        or activation.observation_epoch != 0
        or activation.baseline_close_ms is not None
        or activation.consumption_revision != 0
        or activation.execution_guard_json is not None
        or await model.AccumulationOpportunity.filter(activation=activation)
        .using_db(conn)
        .exists()
    ):
        raise AccumulationConflictError("Unadopted entry identity is inconsistent.")
    commands = (
        await model.AccumulationLifecycleOperation.filter(
            activation=activation,
            status__in=["pending", "quarantined"],
            action__in=RETIRABLE_ACTIONS
            | {"rebind_account", "repair_order", "declare_ownership"},
        )
        .exclude(operation_id=exclude_operation_id or "")
        .using_db(conn)
        .order_by("id")
    )
    for command in commands:
        if (
            command.placement_id is not None
            or command.status == "pending"
            and (
                activation.observations_initialized
                or command.action not in ENTRY_ACTIONS
            )
        ):
            raise AccumulationConflictError(
                "A command with possible execution must be acknowledged or reconciled first."
            )
    return {
        "quantity": inv.quantity,
        "inventory": asdict(inv),
        "holding_id": holding.id if holding is not None else None,
        "history_complete": holding.execution_history_complete
        if holding is not None
        else None,
        "commands": [
            {
                "id": row.id,
                "operation_id": row.operation_id,
                "action": row.action,
                "status": row.status,
                "request_digest": hashlib.sha256(row.request_json.encode()).hexdigest(),
                "result_revision": row.result_revision,
            }
            for row in commands
        ],
        "identity": {
            key: str(getattr(activation, key))
            for key in (
                "generation",
                "strategy_version_id",
                "observation_epoch",
                "baseline_close_ms",
                "observations_initialized",
                "consumption_revision",
                "execution_guard_json",
            )
        },
    }


class AccumulationOwnershipDeclaration:
    """Reassign a declared holding only after explicit review and fresh coverage."""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    async def submit(self, payload: dict[str, Any]) -> Any:
        """Pause before reads, preserve the complete audit, and never enable buys."""
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "symbol",
                "action",
                "operation_id",
                "expected_revision",
                "confirmation",
                "note",
            }
            or payload["action"] != "declare_ownership"
        ):
            raise AccumulationStateError("Invalid ownership-declaration request.")
        if not isinstance(payload["symbol"], str):
            raise AccumulationStateError("Invalid ownership symbol.")
        symbol = normalize_order_symbol(payload["symbol"])
        operation_id = validate_operation_id(payload["operation_id"])
        revision = payload["expected_revision"]
        if type(revision) is not int or not 0 <= revision < 2**63 - 2:
            raise AccumulationStateError("Invalid ownership revision.")
        note = payload["note"]
        if (
            payload["confirmation"] != symbol
            or not isinstance(note, str)
            or not 1 <= len(note.strip()) <= 500
            or any(ord(char) < 32 for char in note)
        ):
            raise AccumulationStateError(
                "Type the full symbol and provide a reason of 1–500 characters."
            )
        command = {**payload, "symbol": symbol, "note": note.strip()}
        config = self.adapter.config()
        scope = await self.adapter.account_scope(config)

        async def stage() -> Any:
            async with in_transaction() as conn:
                prior = await model.AccumulationLifecycleOperation.get_or_none(
                    operation_id=operation_id
                ).using_db(conn)
                if prior is not None:
                    body = json.loads(prior.request_json)
                    if (
                        prior.action != "declare_ownership"
                        or body.get("command") != command
                        or body.get("new_account_scope") != scope
                    ):
                        raise AccumulationConflictError(
                            "Operation ID belongs to another declaration."
                        )
                    return prior
                activation = await model.AccumulationActivation.get_or_none(
                    symbol=symbol
                ).using_db(conn)
                if (
                    activation is None
                    or activation.revision != revision
                    or activation.account_scope == scope
                ):
                    raise AccumulationConflictError(
                        "A changed account scope and current revision are required."
                    )
                if activation.account_scope.startswith(
                    "credential-demo-v1:"
                ) != scope.startswith("credential-demo-v1:"):
                    raise AccumulationConflictError(
                        "Demo and live inventory cannot be rebound or declared across environments."
                    )
                plan = await _plan(activation, conn)
                old_scope, old_state, old_paused = (
                    activation.account_scope,
                    activation.state,
                    activation.explicitly_paused,
                )
                await AccumulationAccountRebind._advance(activation, conn)
                if activation.state not in {"closing", "stopped"}:
                    activation.state = "paused"
                activation.explicitly_paused = True
                activation.reason = "ownership_declaration_pending"
                await activation.save(using_db=conn)
                return await model.AccumulationLifecycleOperation.create(
                    using_db=conn,
                    operation_id=operation_id,
                    activation=activation,
                    action="declare_ownership",
                    status="quarantined",
                    request_json=json.dumps(
                        {
                            "command": command,
                            "old_account_scope": old_scope,
                            "new_account_scope": scope,
                            "plan": plan,
                        },
                        sort_keys=True,
                    ),
                    previous_state=old_state,
                    previous_paused=old_paused,
                    result_state=activation.state,
                    result_revision=activation.revision,
                    reason="fresh_declared_ownership_required",
                )

        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                raise AccumulationConflictError("Trading maintenance is active.")
            receipt = await run_sqlite_write_with_retry(
                stage, "staging explicit ownership declaration"
            )
        if receipt.status == "applied":
            return AccumulationCommandResult.from_operation(receipt)
        if receipt.status != "quarantined":
            raise AccumulationConflictError(
                "Ownership declaration is no longer current."
            )
        request = json.loads(receipt.request_json)
        async with asyncio.timeout(15):
            wallet = await self.adapter.account_inventory(symbol, config)
        if wallet.account_scope != scope or Decimal(
            canonical_decimal(wallet.free_base)
        ) < Decimal(request["plan"]["quantity"]):
            return AccumulationCommandResult.from_operation(
                await model.AccumulationLifecycleOperation.get(
                    operation_id=operation_id
                )
            )

        async def commit() -> Any:
            async with in_transaction() as conn:
                current = await model.AccumulationLifecycleOperation.get(
                    operation_id=operation_id
                ).using_db(conn)
                if current.status == "applied":
                    return AccumulationCommandResult.from_operation(current)
                activation = await model.AccumulationActivation.get(
                    id=current.activation_id
                ).using_db(conn)
                if (
                    current.status != "quarantined"
                    or activation.revision != current.result_revision
                    or activation.account_scope != request["old_account_scope"]
                    or not activation.explicitly_paused
                    or self.adapter.config() != config
                    or not 0 <= self.adapter.clock_ms() - wallet.observed_at_ms <= 10000
                    or await _plan(
                        activation, conn, exclude_operation_id=current.operation_id
                    )
                    != request["plan"]
                ):
                    raise AccumulationConflictError(
                        "Ownership, inventory or evidence changed; declaration was not applied."
                    )
                activation.account_scope = scope
                await AccumulationAccountRebind._advance(activation, conn)
                if activation.holding_id is not None:
                    holding = await model.OpenTrades.get(
                        id=activation.holding_id
                    ).using_db(conn)
                    holding.execution_history_complete = False
                    holding.accumulation_basis_provenance = (
                        "operator_declared_ownership"
                    )
                    await holding.save(using_db=conn)
                if activation.observations_initialized:
                    await (
                        model.AccumulationReturnTotals.filter(activation=activation)
                        .using_db(conn)
                        .update(provenance_complete=False)
                    )
                for previous in request["plan"]["commands"]:
                    reason = (
                        "ownership_scope_redeclared"
                        if not activation.observations_initialized
                        and previous["action"] in ENTRY_ACTIONS
                        else "restore_intent_retired"
                        if previous["action"] in RETIRABLE_ACTIONS
                        else "superseded_by_ownership_declaration"
                    )
                    await (
                        model.AccumulationLifecycleOperation.filter(id=previous["id"])
                        .using_db(conn)
                        .update(
                            status="cancelled",
                            reason=reason,
                            result_state=activation.state,
                            result_revision=activation.revision,
                        )
                    )
                activation.reason = (
                    "ownership_declared_paused"
                    if activation.observations_initialized
                    else "entry_scope_declared_unvalidated"
                )
                await activation.save(using_db=conn)
                current.status, current.reason = "applied", activation.reason
                current.result_state, current.result_revision = (
                    activation.state,
                    activation.revision,
                )
                await current.save(using_db=conn)
                return AccumulationCommandResult.from_operation(current)

        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                raise AccumulationConflictError("Trading maintenance is active.")
            return await run_sqlite_write_with_retry(
                commit, "committing explicit ownership declaration"
            )
