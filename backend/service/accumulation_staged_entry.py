"""Revisioned corrections and operator decisions for inventory not yet adopted."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import model
from service.accumulation_commands import (
    ENTRY_ACTIONS,
    RETIRABLE_ACTIONS,
    AccumulationCommandResult,
    validate_operation_id,
)
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_import import AccumulationImport, parse_accumulation_csv
from service.accumulation_lifecycle import (
    AccumulationLifecycleService,
    _require_settled,
    _validate_scope,
)
from service.accumulation_state import AccumulationConflictError
from service.order_requests import normalize_order_symbol
from tortoise.transactions import in_transaction


@dataclass(frozen=True)
class StagedEntryCommand:
    """Complete request identity, including the exact predecessor shown to a user."""

    symbol: str
    action: str
    operation_id: str
    expected_revision: int
    previous_operation_id: str
    imported_inventory: dict[str, Any] | None
    target_version_id: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, now_ms: int) -> StagedEntryCommand:
        """Validate transport fields and parse corrections before opening a write."""
        fields = {
            "symbol",
            "action",
            "operation_id",
            "expected_revision",
            "previous_operation_id",
        }
        if not isinstance(payload, dict) or not fields <= payload.keys():
            raise AccumulationStateError("Missing staged-entry command fields.")
        action = payload["action"]
        if not isinstance(action, str) or action not in {
            "retry_entry",
            "correct_import",
            "abandon_entry",
        }:
            raise AccumulationStateError("Unsupported staged-entry action.")
        target = payload.get("target_version_id")
        if "target_version_id" in payload:
            if (
                action == "abandon_entry"
                or type(target) is not int
                or not 0 < target < 2**63
            ):
                raise AccumulationStateError(
                    "Select an exact compatible strategy version."
                )
            fields.add("target_version_id")
        if set(payload) != fields | (
            {"csv_content"} if action == "correct_import" else set()
        ):
            raise AccumulationStateError("Unexpected staged-entry command fields.")
        revision = payload["expected_revision"]
        if type(revision) is not int or not 0 < revision < 2**63 - 1:
            raise AccumulationStateError("A positive expected_revision is required.")
        if not isinstance(payload["symbol"], str):
            raise AccumulationStateError("Invalid staged-entry symbol.")
        symbol = normalize_order_symbol(payload["symbol"])
        if len(symbol.split("/")) != 2 or ":" in symbol:
            raise AccumulationStateError("A spot symbol is required.")
        imported = None
        if action == "correct_import":
            declarations = parse_accumulation_csv(
                payload["csv_content"], symbol.split("/")[1], now_ms=now_ms
            )
            if len(declarations) != 1 or declarations[0].symbol != symbol:
                raise AccumulationStateError(
                    "Correction must declare only the staged symbol."
                )
            imported = declarations[0].to_dict()
        operation_id = validate_operation_id(payload["operation_id"])
        previous = validate_operation_id(payload["previous_operation_id"])
        if operation_id == previous:
            raise AccumulationStateError("A new operation_id is required.")
        return cls(symbol, action, operation_id, revision, previous, imported, target)


async def stage_entry_command(
    command: StagedEntryCommand, *, account_scope: str
) -> AccumulationCommandResult:
    """Journal a decision atomically, without wallet reads or exchange effects."""
    _validate_scope(account_scope)
    if command.target_version_id is not None:
        from service.strategy_runtime import load_accumulation_strategy_version

        await load_accumulation_strategy_version(command.target_version_id)
    # JSON normalization also gives tuple/list declarations one retry identity.
    identity = json.loads(
        json.dumps({**asdict(command), "account_scope": account_scope})
    )

    async def persist() -> AccumulationCommandResult:
        async with in_transaction() as connection:
            existing = await model.AccumulationLifecycleOperation.get_or_none(
                operation_id=command.operation_id
            ).using_db(connection)
            if existing is not None:
                if json.loads(existing.request_json).get("staged_command") != identity:
                    raise AccumulationConflictError(
                        "operation_id was already used for a different request."
                    )
                return AccumulationCommandResult.from_operation(existing)
            if command.action in {"retry_entry", "correct_import"} and (
                await model.AppConfig.filter(
                    key="trade_mode", value="dynamic_dca", value_type="str"
                )
                .using_db(connection)
                .exists()
            ):
                # Check committed mode before a stale dashboard can reclaim the
                # symbol. Historical receipts and safe abandonment stay usable.
                raise AccumulationConflictError(
                    "Select Accumulation mode before retrying or correcting entry."
                )
            activation = await model.AccumulationActivation.get_or_none(
                symbol=command.symbol
            ).using_db(connection)
            if activation is None or activation.account_scope != account_scope:
                raise AccumulationStateError(
                    "Entry is missing or account scope changed."
                )
            if activation.revision != command.expected_revision:
                raise AccumulationConflictError(
                    "Stale lifecycle revision; refresh first."
                )
            if (
                activation.state not in {"validating", "paused", "stopped"}
                or activation.holding_id is not None
                or activation.observations_initialized
                or activation.observation_epoch != 0
                or activation.baseline_close_ms is not None
                or activation.consumption_revision != 0
                or activation.execution_guard_json is not None
                or await model.OpenTrades.filter(symbol=command.symbol)
                .using_db(connection)
                .exists()
                or await model.Trades.filter(symbol=command.symbol)
                .using_db(connection)
                .exists()
                or await model.AccumulationOpportunity.filter(activation=activation)
                .using_db(connection)
                .exists()
                or await model.AccumulationFillCheckpoint.filter(activation=activation)
                .using_db(connection)
                .exists()
            ):
                raise AccumulationConflictError(
                    "Only an unadopted entry may be changed."
                )
            await _require_settled(activation, connection)
            previous = (
                await model.AccumulationLifecycleOperation.filter(
                    activation=activation, action__in=ENTRY_ACTIONS | {"abandon_entry"}
                )
                .using_db(connection)
                .order_by("-id")
                .first()
            )
            latest = (
                await model.AccumulationLifecycleOperation.filter(activation=activation)
                .using_db(connection)
                .order_by("-id")
                .first()
            )
            if (
                previous is None
                or previous.operation_id != command.previous_operation_id
            ):
                raise AccumulationConflictError(
                    "Reference the current staged declaration."
                )
            current = (
                (
                    previous.action == "abandon_entry"
                    and previous.status == "applied"
                    and activation.state == "stopped"
                    and latest.id == previous.id
                    and previous.result_revision == activation.revision
                    and command.action in {"retry_entry", "correct_import"}
                )
                or (
                    previous.status == "pending"
                    and previous.result_revision == activation.revision
                    and latest.id == previous.id
                )
                or (
                    previous.status == "cancelled"
                    and previous.reason == "superseded_by_pause"
                    and activation.state == "paused"
                    and latest.action == "pause"
                    and latest.status == "applied"
                    and latest.result_revision == activation.revision
                )
                or (
                    previous.status == "cancelled"
                    and previous.reason == "restore_intent_retired"
                    and activation.state == "paused"
                    and latest.action == "retire_command"
                    and latest.status == "applied"
                    and latest.result_revision == activation.revision
                )
                or (
                    previous.status == "cancelled"
                    and previous.reason == "ownership_scope_redeclared"
                    and activation.state == "paused"
                    and latest.action == "declare_ownership"
                    and latest.status == "applied"
                    and latest.result_revision == activation.revision
                )
            )
            if not current or previous.placement_id is not None:
                raise AccumulationConflictError(
                    "Staged declaration is no longer current."
                )
            if (
                await model.AccumulationLifecycleOperation.filter(
                    activation=activation,
                    status="quarantined",
                    action__in=RETIRABLE_ACTIONS,
                )
                .using_db(connection)
                .exists()
            ):
                raise AccumulationConflictError(
                    "Retire remaining interrupted commands before validating entry."
                )
            if (
                (
                    previous.target_version_id is None
                    and command.target_version_id is None
                )
                or previous.target_version_id != activation.strategy_version_id
                or await model.AccumulationLifecycleOperation.filter(
                    activation=activation, status="pending"
                )
                .exclude(id=previous.id)
                .using_db(connection)
                .exists()
            ):
                raise AccumulationConflictError("Staged ownership requires repair.")
            try:
                request = json.loads(previous.request_json)
                request = request if isinstance(request, dict) else {}
                source = request.get("source")
            except (ValueError, TypeError):
                request, source = {}, None
            if (
                source not in {"asap", "csv"}
                and command.action == "correct_import"
                and previous.action == "abandon_entry"
                and activation.state == "stopped"
            ):
                source = "csv"
            if source not in {"asap", "csv"} and command.action != "abandon_entry":
                raise AccumulationStateError("Unsupported staged source.")
            if command.action == "correct_import" and source != "csv":
                raise AccumulationStateError("Only CSV declarations may be corrected.")
            imported = command.imported_inventory or request.get("imported_inventory")
            if source == "csv" and command.action != "abandon_entry":
                if not isinstance(imported, dict):
                    raise AccumulationStateError(
                        "CSV entry is missing its inventory declaration."
                    )
                declaration = AccumulationImport.from_dict(imported)
                if declaration.symbol != command.symbol:
                    raise AccumulationStateError(
                        "CSV inventory belongs to another symbol."
                    )
            previous_state, previous_paused = (
                activation.state,
                activation.explicitly_paused,
            )
            reason = (
                "entry_abandoned"
                if command.action == "abandon_entry"
                else "validation_required"
            )
            previous.status, previous.reason = "continued", command.action
            await previous.save(using_db=connection)
            activation.state = (
                "stopped" if command.action == "abandon_entry" else "validating"
            )
            activation.explicitly_paused = True
            activation.revision += 1
            activation.strategy_version_id = (
                command.target_version_id or previous.target_version_id
            )
            activation.reason = reason
            await activation.save(using_db=connection)
            request = {
                "staged_command": identity,
                "source": source,
                "imported_inventory": imported,
            }
            operation = await model.AccumulationLifecycleOperation.create(
                using_db=connection,
                activation=activation,
                operation_id=command.operation_id,
                action=command.action,
                request_json=json.dumps(request, sort_keys=True, separators=(",", ":")),
                status="applied" if command.action == "abandon_entry" else "pending",
                previous_state=previous_state,
                previous_paused=previous_paused,
                result_state=activation.state,
                result_revision=activation.revision,
                target_version_id=activation.strategy_version_id,
                reason=reason,
            )
            return AccumulationCommandResult.from_operation(operation)

    return await AccumulationLifecycleService._mutate(command.symbol, persist)
