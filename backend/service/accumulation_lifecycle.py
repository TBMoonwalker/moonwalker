"""Durable accumulation command handling, independent of exchange execution.

Entry adapters and the exchange/accounting worker are intentionally separate.
This service never places orders or assumes that cancellation succeeded.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

import model
from service.accumulation_commands import (
    CLOSE_ACTIONS,
    ENTRY_ACTIONS,
    RETIRABLE_ACTIONS,
    SALE_ACTIONS,
    AccumulationAction,
    AccumulationCommand,
    AccumulationCommandResult,
    validate_operation_id,
)
from service.accumulation_contracts import (
    AccumulationLifecycle,
    AccumulationStateError,
    canonical_decimal,
    encode_observations,
)
from service.accumulation_import import AccumulationImport
from service.accumulation_inventory_evidence import inventory_restore_required
from service.accumulation_state import (
    AccumulationConflictError,
    _load_context,
    load_accumulation_context,
)
from service.capital_budget import CapitalBudgetService
from service.database import run_sqlite_write_with_retry
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.order_requests import normalize_order_symbol
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

_REBASE_ACTIONS = frozenset(
    {"activate", "retry_entry", "resume", "reactivate", "switch_strategy"}
)
_IDLE_STATES = frozenset({"enabled", "paused", "blocked"})


@dataclass(frozen=True)
class AccumulationValidationRequest:
    """Server-owned state a readiness adapter must validate against current inputs."""

    activation_id: str
    symbol: str
    account_scope: str
    target_version_id: int
    revision: int
    consumption_revision: int
    prior_baseline_close_ms: int | None
    imported_inventory: AccumulationImport | None = None
    initial_asap: bool = False


@dataclass(frozen=True)
class AccumulationReadiness:
    """Validated account, compatible strategy and completed-candle warmup result.

    Supplied by a trusted server adapter, never decoded from a dashboard payload.
    No default adapter exists until strategy and ownership validation are wired.
    """

    account_scope: str
    strategy_version_id: int
    baseline_close_ms: int
    observations: dict[str, Any] | None
    # Trusted adapter callback: database/config checks only, never network I/O.
    validate_commit: Callable[[], Awaitable[None]] | None = None


ReadinessValidator = Callable[
    [AccumulationValidationRequest], Awaitable[AccumulationReadiness]
]


def _validate_scope(account_scope: str) -> None:
    if (
        not isinstance(account_scope, str)
        or not account_scope.strip()
        or len(account_scope) > 128
    ):
        raise AccumulationStateError("A bounded account scope is required.")


async def _has_unsettled_execution(
    activation: model.AccumulationActivation, connection: BaseDBAsyncClient
) -> bool:
    # Quarantined and unknown states are NOT proof of terminal zero exposure.
    if (
        await model.PlacementIntent.filter(symbol=activation.symbol)
        .exclude(state__in=("completed", "rejected"))
        .using_db(connection)
        .exists()
    ):
        return True
    if (
        await model.AccumulationOpportunity.filter(unresolved_slot=activation.id)
        .using_db(connection)
        .exists()
    ):
        return True
    return (
        await model.OpenTrades.filter(symbol=activation.symbol)
        .exclude(tp_limit_order_id__isnull=True)
        .exclude(tp_limit_order_id="")
        .using_db(connection)
        .exists()
    )


async def _require_settled(
    activation: model.AccumulationActivation, connection: BaseDBAsyncClient
) -> None:
    if await _has_unsettled_execution(activation, connection):
        raise AccumulationConflictError("Existing orders require reconciliation first.")


async def _require_sale_checkpoint(
    operation: model.AccumulationLifecycleOperation,
    activation: model.AccumulationActivation,
    connection: BaseDBAsyncClient,
) -> None:
    """Require complete accounting proof for the command's own terminal sale."""
    if (
        operation.status == "cancelled"
        and operation.reason == "restore_intent_retired"
        and operation.placement_id is None
        and operation.action in CLOSE_ACTIONS
    ):
        # The explicit retirement transaction verified no unresolved execution.
        # Placement creation and command attachment share one transaction, so
        # this command never authorized an exchange submission.
        return
    placement = await model.PlacementIntent.get_or_none(
        id=operation.placement_id
    ).using_db(connection)
    if (
        placement is None
        or placement.state != "completed"
        or placement.action != "sell"
        or placement.side != "sell"
        or placement.symbol != activation.symbol
    ):
        raise AccumulationConflictError("Confirmed manual-sale accounting is required.")
    checkpoint = await model.AccumulationFillCheckpoint.get_or_none(
        placement=placement
    ).using_db(connection)
    if (
        checkpoint is None
        or checkpoint.activation_id != activation.id
        or not checkpoint.terminal
        or not checkpoint.fees_complete
    ):
        raise AccumulationConflictError(
            "Complete manual-sale accounting checkpoint is required."
        )
    try:
        request = json.loads(placement.request_json)
    except (TypeError, ValueError) as exc:
        raise AccumulationStateError("Corrupt sale intent context.") from exc
    if (
        not isinstance(request, dict)
        or request.get("accumulation_operation_id") != operation.operation_id
        or request.get("accumulation_action") != operation.action
    ):
        raise AccumulationConflictError(
            "Placement does not authorize this manual sale."
        )


class AccumulationLifecycleService:
    """Serialize and journal operator intent before future execution admission."""

    def __init__(self, validator: ReadinessValidator | None = None) -> None:
        self._validator = validator

    async def rebase_enabled(self, activation_id: str, *, account_scope: str) -> None:
        """Rebuild observations after downtime without enabling or buying anything."""
        context = await load_accumulation_context(activation_id, account_scope)
        activation = await model.AccumulationActivation.get(id=activation_id)
        symbol = activation.symbol
        expected = context.identity
        if (
            expected.state != "enabled"
            or expected.explicitly_paused
            or self._validator is None
        ):
            raise AccumulationConflictError("Only an enabled activation can rebase.")
        request = AccumulationValidationRequest(
            activation_id,
            symbol,
            account_scope,
            expected.strategy_version_id,
            expected.revision,
            expected.consumption_revision,
            expected.baseline_close_ms,
        )
        ready = await self._validator(request)
        if (
            ready.account_scope != account_scope
            or ready.strategy_version_id != expected.strategy_version_id
            or type(ready.baseline_close_ms) is not int
            or ready.baseline_close_ms
            < (context.last_processed_close_ms or expected.baseline_close_ms)
        ):
            raise AccumulationStateError("Rebase identity or baseline changed.")
        observations = encode_observations(ready.observations)

        async def persist() -> None:
            async with in_transaction() as connection:
                current = await _load_context(activation_id, account_scope, connection)
                if current.identity != expected:
                    raise AccumulationConflictError(
                        "Lifecycle changed during runtime rebase."
                    )
                activation = await model.AccumulationActivation.get(
                    id=activation_id
                ).using_db(connection)
                await _require_settled(activation, connection)
                if (
                    await model.AccumulationLifecycleOperation.filter(
                        activation=activation, status="pending"
                    )
                    .using_db(connection)
                    .exists()
                ):
                    raise AccumulationConflictError(
                        "Operator work must settle before rebase."
                    )
                activation.baseline_close_ms = ready.baseline_close_ms
                activation.observation_epoch += 1
                activation.observations_initialized = True
                activation.revision += 1
                await activation.save(using_db=connection)
                await model.AccumulationStrategyState.create(
                    using_db=connection,
                    activation=activation,
                    strategy_version_id=ready.strategy_version_id,
                    observation_epoch=activation.observation_epoch,
                    value_json=observations,
                    last_processed_close_ms=ready.baseline_close_ms,
                    revision=activation.revision,
                )

        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                raise AccumulationConflictError("Maintenance is active.")
            await run_sqlite_write_with_retry(
                persist, "rebasing accumulation after downtime"
            )

    async def stage_activation(
        self,
        *,
        symbol: str,
        account_scope: str,
        strategy_version_id: int,
        source: str,
        operation_id: str,
        imported_inventory: AccumulationImport | None = None,
    ) -> AccumulationCommandResult:
        """Stage an ASAP/CSV binding; no inventory or executable holding is invented."""
        symbol = normalize_order_symbol(symbol)
        _validate_scope(account_scope)
        validate_operation_id(operation_id)
        if source not in {"asap", "csv"}:
            raise AccumulationStateError("Accumulation requires ASAP or CSV entry.")
        if (source == "csv") != (imported_inventory is not None):
            raise AccumulationStateError(
                "CSV activation requires its inventory declaration."
            )
        if imported_inventory is not None:
            imported_inventory = AccumulationImport.from_dict(
                imported_inventory.to_dict()
            )
            if imported_inventory.symbol != symbol:
                raise AccumulationStateError("CSV inventory belongs to another symbol.")
        if type(strategy_version_id) is not int or strategy_version_id < 1:
            raise AccumulationStateError("An exact strategy version is required.")
        request_json = json.dumps(
            {
                "symbol": symbol,
                "account_scope": account_scope,
                "strategy_version_id": strategy_version_id,
                "source": source,
                "action": "activate",
                "operation_id": operation_id,
                **(
                    {"imported_inventory": imported_inventory.to_dict()}
                    if imported_inventory
                    else {}
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        async def persist() -> AccumulationCommandResult:
            async with in_transaction() as connection:
                prior = await self._retry(operation_id, request_json, connection)
                if prior is not None:
                    return prior
                if (
                    await model.AccumulationActivation.filter(symbol=symbol)
                    .using_db(connection)
                    .exists()
                ):
                    raise AccumulationConflictError(
                        "Symbol already has an activation; use explicit lifecycle actions."
                    )
                if (
                    await model.OpenTrades.filter(symbol=symbol)
                    .using_db(connection)
                    .exists()
                ):
                    raise AccumulationConflictError(
                        "Existing holdings cannot be converted to accumulation."
                    )
                if (
                    await model.Trades.filter(symbol=symbol)
                    .using_db(connection)
                    .exists()
                ):
                    raise AccumulationConflictError(
                        "Existing trade ledger requires reconciliation before entry."
                    )
                version = await model.StrategyVersion.get_or_none(
                    id=strategy_version_id
                ).using_db(connection)
                if version is None:
                    raise AccumulationStateError(
                        "Pinned strategy version does not exist."
                    )
                activation = await model.AccumulationActivation.create(
                    using_db=connection,
                    symbol=symbol,
                    account_scope=account_scope,
                    strategy_version_id=version.id,
                    state="validating",
                    explicitly_paused=True,
                    reason="validation_required",
                    revision=1,
                )
                await model.AccumulationReturnTotals.create(
                    activation=activation, using_db=connection
                )
                await _require_settled(activation, connection)
                operation = await model.AccumulationLifecycleOperation.create(
                    using_db=connection,
                    operation_id=operation_id,
                    activation=activation,
                    action="activate",
                    request_json=request_json,
                    previous_state="validating",
                    previous_paused=False,
                    result_state="validating",
                    result_revision=1,
                    target_version_id=version.id,
                    reason="validation_required",
                )
                return AccumulationCommandResult.from_operation(operation)

        return await self._mutate(symbol, persist)

    async def submit(
        self, payload: dict[str, Any], *, account_scope: str
    ) -> AccumulationCommandResult:
        """Persist an idempotent revision-checked command, without exchange effects."""
        command = AccumulationCommand.from_dict(payload)
        if command.action == AccumulationAction.ARCHIVE_DUST:
            raise AccumulationStateError(
                "Dust archival requires fresh exchange evidence."
            )
        _validate_scope(account_scope)
        request_json = command.request_json(account_scope)

        async def persist() -> AccumulationCommandResult:
            async with in_transaction() as connection:
                prior = await self._retry(
                    command.operation_id, request_json, connection
                )
                if prior is not None:
                    return prior
                activation = await model.AccumulationActivation.get_or_none(
                    symbol=command.symbol
                ).using_db(connection)
                if activation is None or activation.account_scope != account_scope:
                    raise AccumulationStateError(
                        "Activation is missing or account scope changed."
                    )
                AccumulationLifecycle(activation.state)
                if activation.revision != command.expected_revision:
                    raise AccumulationConflictError(
                        "Stale lifecycle revision; refresh before retrying."
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
                        "Retire or reconcile interrupted restore commands first."
                    )
                pending = await model.AccumulationLifecycleOperation.filter(
                    activation=activation,
                    status__in=(
                        ["pending", "reconciled"]
                        if command.action == AccumulationAction.RETRY_CLOSE
                        else ["pending"]
                    ),
                ).using_db(connection)
                if command.action == AccumulationAction.RETRY_CLOSE:
                    retired = await model.AccumulationLifecycleOperation.get_or_none(
                        activation=activation,
                        operation_id=command.previous_operation_id,
                        status="cancelled",
                        action__in=CLOSE_ACTIONS,
                        reason="restore_intent_retired",
                        placement_id__isnull=True,
                        result_revision=activation.revision,
                    ).using_db(connection)
                    if retired is not None:
                        pending.append(retired)
                if command.action == AccumulationAction.RETRY_CLOSE:
                    if (
                        activation.state != "closing"
                        or len(pending) != 1
                        or pending[0].operation_id != command.previous_operation_id
                        or pending[0].action not in CLOSE_ACTIONS
                        or pending[0].result_revision != activation.revision
                    ):
                        raise AccumulationConflictError(
                            "Retry close must reference the current pending close."
                        )
                    await _require_settled(activation, connection)
                    await _require_sale_checkpoint(pending[0], activation, connection)
                    pending[0].status = "continued"
                    pending[0].reason = "explicit_close_retry"
                    await pending[0].save(using_db=connection)
                elif pending:
                    if command.action != AccumulationAction.PAUSE or any(
                        row.action not in _REBASE_ACTIONS | ENTRY_ACTIONS
                        or row.placement_id is not None
                        for row in pending
                    ):
                        raise AccumulationConflictError(
                            "A lifecycle operation is already pending."
                        )
                    for row in pending:
                        row.status = "cancelled"
                        row.reason = "superseded_by_pause"
                        await row.save(using_db=connection)
                previous_state, previous_paused = (
                    activation.state,
                    activation.explicitly_paused,
                )
                status, reason = await self._apply_command(
                    command, activation, connection
                )
                activation.revision += 1
                activation.reason = reason
                await activation.save(using_db=connection)
                operation = await model.AccumulationLifecycleOperation.create(
                    using_db=connection,
                    operation_id=command.operation_id,
                    activation=activation,
                    action=command.action.value,
                    request_json=request_json,
                    status=status,
                    previous_state=previous_state,
                    previous_paused=previous_paused,
                    result_state=activation.state,
                    result_revision=activation.revision,
                    target_version_id=command.target_version_id,
                    requested_quantity=command.quantity,
                    reason=reason,
                )
                return AccumulationCommandResult.from_operation(operation)

        return await self._mutate(command.symbol, persist)

    async def _apply_command(
        self,
        command: AccumulationCommand,
        activation: model.AccumulationActivation,
        connection: BaseDBAsyncClient,
    ) -> tuple[str, str | None]:
        action = command.action
        if (
            action
            in {
                AccumulationAction.RESUME,
                AccumulationAction.REACTIVATE,
                AccumulationAction.SWITCH_STRATEGY,
            }
            and not activation.observations_initialized
        ):
            # A paused/abandoned declaration is not an empty, adopted holding.
            # Entry commands preserve its inventory and exact strategy binding.
            raise AccumulationConflictError(
                "Unvalidated entry requires explicit staged-entry controls."
            )
        if action == AccumulationAction.PAUSE:
            if activation.state in {"closing", "selling_partial", "stopped"}:
                raise AccumulationConflictError("This lifecycle cannot be paused.")
            activation.state, activation.explicitly_paused = "paused", True
            if await _has_unsettled_execution(activation, connection):
                return "pending", "cancellation_and_reconciliation_required"
            return "applied", None
        if action == AccumulationAction.REACTIVATE:
            if activation.state != "stopped" or activation.holding_id is not None:
                raise AccumulationConflictError(
                    "Reactivate requires a fully stopped, empty holding."
                )
            await _require_settled(activation, connection)
            activation.generation = uuid4()
            # A completed holding starts a new purchase cycle. Historical orders
            # retain their generation; only the new cycle's execution guards reset.
            activation.consumption_revision = 0
            activation.execution_guard_json = None
            activation.state, activation.explicitly_paused = "validating", True
            return "pending", "validation_required"
        if action == AccumulationAction.RESUME:
            if activation.state != "paused":
                raise AccumulationConflictError(
                    "Resume requires an explicitly paused activation."
                )
            await _require_settled(activation, connection)
            activation.state = "validating"
            return "pending", "validation_required"
        if activation.state not in _IDLE_STATES and not (
            action == AccumulationAction.RETRY_CLOSE and activation.state == "closing"
        ):
            raise AccumulationConflictError(
                "This lifecycle already has work in progress."
            )
        if action == AccumulationAction.SWITCH_STRATEGY:
            if activation.state == "blocked":
                raise AccumulationConflictError(
                    "Repair blocked ownership before switching strategy."
                )
            version = await model.StrategyVersion.get_or_none(
                id=command.target_version_id
            ).using_db(connection)
            if version is None:
                raise AccumulationStateError("Target strategy version does not exist.")
            activation.state = "switching"
            return "pending", "settlement_and_validation_required"
        holding = await model.OpenTrades.get_or_none(id=activation.holding_id).using_db(
            connection
        )
        if (
            action == AccumulationAction.CLOSE
            and holding is None
            and activation.holding_id is None
        ):
            await _require_settled(activation, connection)
            if (
                not activation.observations_initialized
                or await inventory_restore_required(activation, connection)
                or await model.OpenTrades.filter(symbol=activation.symbol)
                .using_db(connection)
                .exists()
            ):
                raise AccumulationConflictError(
                    "Restore recorded inventory before stopping this registration."
                )
            activation.state, activation.explicitly_paused = "stopped", True
            return "applied", "empty_registration_stopped"
        if (
            holding is None
            or holding.symbol != activation.symbol
            or holding.lifecycle_mode != "accumulation"
        ):
            raise AccumulationConflictError(
                "An owned accumulation holding is required to sell."
            )
        if action in CLOSE_ACTIONS:
            canonical_decimal(holding.accumulation_net_quantity, positive=True)
            activation.state = "closing"
            return "pending", "settlement_and_manual_execution_required"
        if activation.state == "blocked":
            raise AccumulationConflictError(
                "Repair blocked ownership before a partial sale."
            )
        quantity = Decimal(
            canonical_decimal(holding.accumulation_net_quantity, positive=True)
        )
        if Decimal(command.quantity) >= quantity:
            raise AccumulationStateError(
                "Partial quantity must be less than the holding; use Full close."
            )
        activation.state = "selling_partial"
        return "pending", "settlement_and_manual_execution_required"

    @staticmethod
    async def _retry(
        operation_id: str, request_json: str, connection: BaseDBAsyncClient
    ) -> AccumulationCommandResult | None:
        prior = await model.AccumulationLifecycleOperation.get_or_none(
            operation_id=operation_id
        ).using_db(connection)
        if prior is None:
            return None
        if prior.request_json != request_json:
            raise AccumulationConflictError(
                "operation_id was already used for a different request."
            )
        return AccumulationCommandResult.from_operation(prior)

    @staticmethod
    async def _mutate(
        symbol: str, persist: Callable[[], Awaitable[AccumulationCommandResult]]
    ) -> AccumulationCommandResult:
        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                raise AccumulationConflictError(
                    "Lifecycle changes are paused during maintenance."
                )
            return await run_sqlite_write_with_retry(
                persist, "updating accumulation lifecycle"
            )

    async def _load_completion(
        self, operation_id: str, account_scope: str, connection: BaseDBAsyncClient
    ) -> tuple[model.AccumulationLifecycleOperation, model.AccumulationActivation]:
        operation = await model.AccumulationLifecycleOperation.get_or_none(
            operation_id=operation_id
        ).using_db(connection)
        if operation is None:
            raise AccumulationStateError("Lifecycle operation was not found.")
        activation = await model.AccumulationActivation.get(
            id=operation.activation_id
        ).using_db(connection)
        if activation.account_scope != account_scope:
            raise AccumulationStateError("Account scope changed.")
        # Completion retries return the journaled outcome even if a newer
        # operator command has since advanced the activation.
        if operation.status == "applied":
            return operation, activation
        if operation.status != "pending" or (
            operation.result_revision != activation.revision
        ):
            raise AccumulationConflictError("Lifecycle operation is no longer current.")
        return operation, activation

    async def complete_rebase(
        self, operation_id: str, *, account_scope: str
    ) -> AccumulationCommandResult:
        """Validate outside the transaction, then atomically rebase if still current."""
        async with in_transaction() as connection:
            operation, activation = await self._load_completion(
                operation_id, account_scope, connection
            )
            if operation.action not in _REBASE_ACTIONS:
                raise AccumulationStateError(
                    "This operation does not rebase a strategy."
                )
            if operation.status == "applied":
                return AccumulationCommandResult.from_operation(operation)
            if self._validator is None:
                raise AccumulationStateError(
                    "Readiness validation is not connected yet."
                )
            await _require_settled(activation, connection)
            activation_request = json.loads(operation.request_json)
            imported_payload = (
                activation_request.get("imported_inventory")
                if operation.action in ENTRY_ACTIONS
                else None
            )
            if (
                operation.action in ENTRY_ACTIONS
                and activation_request.get("source") == "csv"
                and not isinstance(imported_payload, dict)
            ):
                raise AccumulationStateError(
                    "CSV activation is missing its inventory declaration."
                )
            request = AccumulationValidationRequest(
                str(activation.id),
                activation.symbol,
                account_scope,
                operation.target_version_id or activation.strategy_version_id,
                activation.revision,
                activation.consumption_revision,
                activation.baseline_close_ms,
                AccumulationImport.from_dict(imported_payload)
                if imported_payload is not None
                else None,
                initial_asap=(
                    operation.action in ENTRY_ACTIONS
                    and activation_request.get("source") == "asap"
                    and activation.holding_id is None
                    and activation.consumption_revision == 0
                    and activation.baseline_close_ms is None
                ),
            )
        ready = await self._validator(request)
        if (
            ready.account_scope != account_scope
            or ready.strategy_version_id != request.target_version_id
        ):
            raise AccumulationStateError(
                "Readiness result belongs to another account or version."
            )
        if type(ready.baseline_close_ms) is not int or ready.baseline_close_ms < (
            request.prior_baseline_close_ms or 0
        ):
            raise AccumulationStateError("Readiness baseline cannot move backward.")
        if ready.observations is None and not request.initial_asap:
            raise AccumulationStateError("Strategy observations are required.")
        observations = (
            encode_observations(ready.observations)
            if ready.observations is not None
            else None
        )

        async def persist() -> AccumulationCommandResult:
            async with in_transaction() as connection:
                operation, activation = await self._load_completion(
                    operation_id, account_scope, connection
                )
                if operation.status == "applied":
                    return AccumulationCommandResult.from_operation(operation)
                if (
                    activation.revision != request.revision
                    or activation.consumption_revision != request.consumption_revision
                ):
                    raise AccumulationConflictError(
                        "State changed during readiness validation."
                    )
                await _require_settled(activation, connection)
                if (
                    request.imported_inventory is not None
                    and ready.validate_commit is None
                ):
                    raise AccumulationStateError(
                        "CSV ownership commit validation is required."
                    )
                if ready.validate_commit is not None:
                    await ready.validate_commit()
                if request.imported_inventory is not None:
                    imported = request.imported_inventory
                    if (
                        activation.holding_id is not None
                        or await model.OpenTrades.filter(symbol=activation.symbol)
                        .using_db(connection)
                        .exists()
                        or await model.Trades.filter(symbol=activation.symbol)
                        .using_db(connection)
                        .exists()
                    ):
                        raise AccumulationConflictError(
                            "CSV inventory is already managed."
                        )
                    holding = await model.OpenTrades.create(
                        using_db=connection,
                        symbol=activation.symbol,
                        deal_id=str(uuid4()),
                        lifecycle_mode="accumulation",
                        execution_history_complete=False,
                        open_date=datetime.fromtimestamp(
                            imported.entries[0][0] / 1000, timezone.utc
                        ).isoformat(),
                        amount=float(imported.quantity),
                        cost=float(imported.cost),
                        avg_price=float(
                            Decimal(imported.cost) / Decimal(imported.quantity)
                        ),
                        accumulation_net_quantity=imported.quantity,
                        accumulation_remaining_cost=imported.cost,
                        accumulation_contributed_quote=imported.cost,
                        accumulation_disposal_proceeds="0",
                        accumulation_fees_json=json.dumps(
                            {"totals": {}, "pending_reports": len(imported.entries)}
                        ),
                        accumulation_basis_provenance="csv_declared_fees_unknown",
                    )
                    activation.holding_id = holding.id
                    await (
                        model.AccumulationReturnTotals.filter(activation=activation)
                        .using_db(connection)
                        .update(
                            provenance_complete=False,
                            last_quantity=imported.quantity,
                            last_cost=imported.cost,
                        )
                    )
                activation.strategy_version_id = ready.strategy_version_id
                activation.observation_epoch += 1
                activation.baseline_close_ms = ready.baseline_close_ms
                activation.observations_initialized = observations is not None
                activation.explicitly_paused = (
                    operation.previous_paused
                    if operation.action == "switch_strategy"
                    else False
                )
                activation.state = (
                    "paused" if activation.explicitly_paused else "enabled"
                )
                activation.reason = None
                activation.revision += 1
                await activation.save(using_db=connection)
                if observations is not None:
                    await model.AccumulationStrategyState.create(
                        using_db=connection,
                        activation=activation,
                        strategy_version_id=ready.strategy_version_id,
                        observation_epoch=activation.observation_epoch,
                        value_json=observations,
                        last_processed_close_ms=ready.baseline_close_ms,
                        revision=activation.revision,
                    )
                return await self._finish(operation, activation, connection)

        async def commit() -> AccumulationCommandResult:
            async with CapitalBudgetService._lock:
                return await persist()

        return await self._mutate(request.symbol, commit)

    async def complete_settlement(
        self, operation_id: str, *, account_scope: str
    ) -> AccumulationCommandResult:
        """Finalize pause or manual sale only after persisted reconciliation proof."""
        operation = await model.AccumulationLifecycleOperation.get_or_none(
            operation_id=operation_id
        )
        if operation is None:
            raise AccumulationStateError("Lifecycle operation was not found.")
        activation = await model.AccumulationActivation.get(id=operation.activation_id)

        async def persist() -> AccumulationCommandResult:
            async with in_transaction() as connection:
                operation, activation = await self._load_completion(
                    operation_id, account_scope, connection
                )
                if operation.action not in SALE_ACTIONS | {"pause"}:
                    raise AccumulationStateError(
                        "This operation requires readiness validation."
                    )
                if operation.status == "applied":
                    return AccumulationCommandResult.from_operation(operation)
                await _require_settled(activation, connection)
                if operation.action in SALE_ACTIONS:
                    await _require_sale_checkpoint(operation, activation, connection)
                    holding = await model.OpenTrades.get_or_none(
                        symbol=activation.symbol
                    ).using_db(connection)
                    if operation.action in CLOSE_ACTIONS:
                        if holding is not None:
                            raise AccumulationConflictError(
                                "Full close has a remaining holding or dust."
                            )
                        activation.state, activation.explicitly_paused = "stopped", True
                    else:
                        if holding is None or holding.id != activation.holding_id:
                            raise AccumulationConflictError(
                                "Partial sale must retain its owned holding."
                            )
                        canonical_decimal(
                            holding.accumulation_net_quantity, positive=True
                        )
                        activation.state = operation.previous_state
                        activation.explicitly_paused = operation.previous_paused
                activation.reason = None
                activation.revision += 1
                await activation.save(using_db=connection)
                return await self._finish(operation, activation, connection)

        return await self._mutate(activation.symbol, persist)

    @staticmethod
    async def _finish(
        operation: model.AccumulationLifecycleOperation,
        activation: model.AccumulationActivation,
        connection: BaseDBAsyncClient,
    ) -> AccumulationCommandResult:
        operation.status, operation.reason = "applied", None
        operation.result_state, operation.result_revision = (
            activation.state,
            activation.revision,
        )
        operation.updated_at = datetime.now(timezone.utc)
        await operation.save(using_db=connection)
        return AccumulationCommandResult.from_operation(operation)
