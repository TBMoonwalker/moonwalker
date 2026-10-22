"""Paused, wallet-validated inventory declarations, separate from exchange fills."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Any

import model
from service.accumulation_accounting import _inventory
from service.accumulation_commands import validate_operation_id
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_lifecycle import _require_settled, _result
from service.accumulation_ownership_evidence import declared_unknown_fee_count
from service.accumulation_state import AccumulationConflictError
from service.database import run_sqlite_write_with_retry
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.order_requests import normalize_order_symbol
from tortoise.transactions import in_transaction


async def _snapshot(
    symbol: str, scope: str, revision: int, conn: Any
) -> tuple[Any, Any, dict[str, Any]]:
    activation = await model.AccumulationActivation.get_or_none(symbol=symbol).using_db(
        conn
    )
    holding = await model.OpenTrades.get_or_none(symbol=symbol).using_db(conn)
    if (
        activation is None
        or activation.account_scope != scope
        or activation.revision != revision
        or activation.state != "paused"
        or not activation.explicitly_paused
        or not activation.observations_initialized
        or holding is None
        or holding.id != activation.holding_id
        or holding.lifecycle_mode != "accumulation"
    ):
        raise AccumulationConflictError(
            "Adjustment requires current, explicitly paused ownership in the configured account."
        )
    await _require_settled(activation, conn)
    if (
        await model.AccumulationFillCheckpoint.filter(
            activation=activation, terminal=False
        )
        .using_db(conn)
        .exists()
        or await model.AccumulationFillCheckpoint.filter(
            activation=activation, fees_complete=False
        )
        .using_db(conn)
        .exists()
    ):
        raise AccumulationConflictError(
            "Complete terminal execution evidence before adjusting inventory."
        )
    if (
        await model.AccumulationLifecycleOperation.filter(
            activation=activation, status__in=["pending", "quarantined"]
        )
        .using_db(conn)
        .exists()
    ):
        raise AccumulationConflictError(
            "Reconcile or retire outstanding commands before adjusting inventory."
        )
    base = symbol.split("/")[0]
    if (
        await model.OpenTrades.filter(symbol__startswith=base + "/")
        .exclude(symbol=symbol)
        .using_db(conn)
        .exists()
    ):
        raise AccumulationConflictError(
            "Shared base-asset ownership requires separate repair."
        )
    inventory = _inventory(holding)
    if inventory.pending_fee_reports and (
        holding.execution_history_complete
        or inventory.pending_fee_reports
        != await declared_unknown_fee_count(activation, conn)
    ):
        raise AccumulationConflictError(
            "Complete pending execution fee evidence first."
        )
    return (
        activation,
        holding,
        {
            "holding_id": holding.id,
            "deal_id": holding.deal_id,
            "inventory": asdict(inventory),
            "history_complete": holding.execution_history_complete,
            "generation": str(activation.generation),
            "strategy_version_id": activation.strategy_version_id,
            "observation_epoch": activation.observation_epoch,
            "baseline_close_ms": activation.baseline_close_ms,
            "consumption_revision": activation.consumption_revision,
            "execution_guard_json": activation.execution_guard_json,
        },
    )


def _adjust(before: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    result = dict(before)
    with localcontext() as context:
        context.prec = 512
        quantity, amount = Decimal(before["quantity"]), Decimal(command["quantity"])
        basis = (
            Decimal(before["remaining_cost"])
            if before["remaining_cost"] is not None
            else None
        )
        contributed = (
            Decimal(before["contributed_quote"])
            if before["contributed_quote"] is not None
            else None
        )
        if command["direction"] == "add":
            cost = (
                Decimal(command["acquisition_cost"])
                if command["acquisition_cost"] is not None
                else None
            )
            quantity += amount
            basis = basis + cost if basis is not None and cost is not None else None
            contributed = (
                contributed + cost
                if contributed is not None and cost is not None
                else None
            )
        else:
            if amount >= quantity:
                raise AccumulationStateError(
                    "A correction must retain positive inventory; it cannot write off a holding or closing dust."
                )
            if basis is not None:
                allocated = (basis * amount / quantity).quantize(
                    Decimal("1e-36"), rounding=ROUND_DOWN
                )
                basis -= allocated
            quantity -= amount
        result.update(
            quantity=canonical_decimal(format(quantity, "f"), positive=True),
            remaining_cost=canonical_decimal(format(basis, "f"))
            if basis is not None
            else None,
            contributed_quote=canonical_decimal(format(contributed, "f"))
            if contributed is not None
            else None,
            basis_provenance="operator_adjusted",
        )
    return result


class AccumulationInventoryAdjustment:
    """Apply one explicit declaration atomically; never trade or resume buying."""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    async def submit(self, payload: dict[str, Any]) -> Any:
        """Validate exact request, read fresh wallet evidence, then recheck and commit."""
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "symbol",
                "action",
                "operation_id",
                "expected_revision",
                "direction",
                "quantity",
                "acquisition_cost",
                "note",
            }
            or payload["action"] != "adjust_inventory"
        ):
            raise AccumulationStateError("Invalid inventory-adjustment request.")
        if not isinstance(payload["symbol"], str):
            raise AccumulationStateError("Invalid adjustment symbol.")
        symbol = normalize_order_symbol(payload["symbol"])
        operation_id = validate_operation_id(payload["operation_id"])
        revision = payload["expected_revision"]
        if type(revision) is not int or not 0 <= revision < 2**63 - 1:
            raise AccumulationStateError("Invalid adjustment revision.")
        if payload["direction"] not in ("add", "remove"):
            raise AccumulationStateError("Select add or remove.")
        amount = canonical_decimal(payload["quantity"], positive=True)
        cost = payload["acquisition_cost"]
        if payload["direction"] == "remove" and cost is not None:
            raise AccumulationStateError(
                "Removal allocates existing weighted basis; acquisition cost must be null."
            )
        if cost is not None:
            cost = canonical_decimal(cost)
        note = payload["note"]
        if (
            not isinstance(note, str)
            or not 1 <= len(note.strip()) <= 500
            or any(ord(char) < 32 for char in note)
        ):
            raise AccumulationStateError(
                "A correction reason of 1–500 characters without control characters is required."
            )
        command = {
            **payload,
            "symbol": symbol,
            "quantity": amount,
            "acquisition_cost": cost,
            "note": note.strip(),
        }
        config = self.adapter.config()
        scope = await self.adapter.account_scope(config)

        async def prior(conn: Any) -> Any:
            row = await model.AccumulationLifecycleOperation.get_or_none(
                operation_id=operation_id
            ).using_db(conn)
            if row is not None:
                request = json.loads(row.request_json)
                if (
                    row.action != "adjust_inventory"
                    or request.get("command") != command
                    or request.get("account_scope") != scope
                ):
                    raise AccumulationConflictError(
                        "Operation ID belongs to another request."
                    )
            return row

        async with in_transaction() as conn:
            recorded = await prior(conn)
            if recorded is not None:
                return _result(recorded)
            _, _, snapshot = await _snapshot(symbol, scope, revision, conn)
        after = _adjust(snapshot["inventory"], command)
        # No database transaction or symbol lock is held over signed network reads.
        async with asyncio.timeout(15):
            wallet = await self.adapter.account_inventory(symbol, config)
        if wallet.account_scope != scope or Decimal(
            canonical_decimal(wallet.free_base)
        ) < Decimal(after["quantity"]):
            raise AccumulationConflictError(
                "Free wallet inventory does not cover the corrected quantity."
            )

        async def commit() -> Any:
            async with in_transaction() as conn:
                recorded = await prior(conn)
                if recorded is not None:
                    return _result(recorded)
                activation, holding, current = await _snapshot(
                    symbol, scope, revision, conn
                )
                if (
                    current != snapshot
                    or self.adapter.config() != config
                    or not 0 <= self.adapter.clock_ms() - wallet.observed_at_ms <= 10000
                ):
                    raise AccumulationConflictError(
                        "Inventory, configuration or wallet evidence changed; refresh before correcting."
                    )
                holding.accumulation_net_quantity = after["quantity"]
                holding.accumulation_remaining_cost = after["remaining_cost"]
                holding.accumulation_contributed_quote = after["contributed_quote"]
                holding.accumulation_basis_provenance = "operator_adjusted"
                holding.execution_history_complete = False
                holding.amount = float(after["quantity"])
                holding.cost = (
                    float(after["remaining_cost"])
                    if after["remaining_cost"] is not None
                    else 0.0
                )
                holding.avg_price = (
                    holding.cost / holding.amount if holding.amount else 0.0
                )
                await holding.save(using_db=conn)
                await (
                    model.AccumulationReturnTotals.filter(activation=activation)
                    .using_db(conn)
                    .update(
                        provenance_complete=False,
                        last_quantity=after["quantity"],
                        last_cost=after["remaining_cost"],
                    )
                )
                activation.revision += 1
                activation.reason = "inventory_adjusted_paused"
                await activation.save(using_db=conn)
                row = await model.AccumulationLifecycleOperation.create(
                    using_db=conn,
                    operation_id=operation_id,
                    activation=activation,
                    action="adjust_inventory",
                    status="applied",
                    request_json=json.dumps(
                        {
                            "command": command,
                            "account_scope": scope,
                            "before": snapshot,
                            "after": after,
                        },
                        sort_keys=True,
                    ),
                    previous_state="paused",
                    previous_paused=True,
                    result_state="paused",
                    result_revision=activation.revision,
                    reason="inventory_adjusted_paused",
                )
                return _result(row)

        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                raise AccumulationConflictError("Trading maintenance is active.")
            return await run_sqlite_write_with_retry(
                commit, "adjusting accumulation inventory"
            )
