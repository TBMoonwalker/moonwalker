"""Restore a missing inventory link from server-held audit evidence only."""

import asyncio
import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any

import model
from service.accumulation_account_rebind import AccumulationAccountRebind
from service.accumulation_accounting import _inventory
from service.accumulation_commands import (
    ENTRY_ACTIONS,
    AccumulationCommandResult,
    validate_operation_id,
)
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_fill import AccumulationInventory
from service.accumulation_import import AccumulationImport
from service.accumulation_lifecycle import _require_settled
from service.accumulation_state import AccumulationConflictError
from service.database import run_sqlite_write_with_retry
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.order_requests import normalize_order_symbol
from tortoise.transactions import in_transaction


async def _evidence(activation: Any, conn: Any) -> dict[str, Any]:
    await _require_settled(activation, conn)
    if (
        await model.AccumulationFillCheckpoint.filter(
            activation=activation, fees_complete=False
        )
        .using_db(conn)
        .exists()
    ):
        raise AccumulationConflictError("Reconcile incomplete fill fees first.")
    checkpoint = (
        await model.AccumulationFillCheckpoint.filter(activation=activation)
        .using_db(conn)
        .order_by("-updated_at", "-id")
        .first()
    )
    adjustment = (
        await model.AccumulationLifecycleOperation.filter(
            activation=activation, action="adjust_inventory", status="applied"
        )
        .using_db(conn)
        .order_by("-id")
        .first()
    )
    deal_id, complete = None, False
    try:
        if adjustment is not None and (
            checkpoint is None or adjustment.updated_at > checkpoint.updated_at
        ):
            receipt = json.loads(adjustment.request_json)
            values = receipt["after"]
            deal_id = receipt["before"]["deal_id"]
        elif checkpoint is not None:
            if not checkpoint.terminal or not checkpoint.fees_complete:
                raise ValueError("Unsettled checkpoint")
            values = json.loads(checkpoint.inventory_json or "null")
            deal_id = checkpoint.deal_id
            complete = adjustment is None
        else:
            entry = (
                await model.AccumulationLifecycleOperation.filter(
                    activation=activation, action__in=ENTRY_ACTIONS, status="applied"
                )
                .using_db(conn)
                .order_by("-id")
                .first()
            )
            request = json.loads(entry.request_json) if entry else {}
            if request.get("source") != "csv":
                raise ValueError("No inventory evidence")
            imported = AccumulationImport.from_dict(request["imported_inventory"])
            if imported.symbol != activation.symbol:
                raise ValueError("Wrong symbol")
            values = asdict(imported.inventory())
            deal_id = request.get("_csv_deal_id")
        if not isinstance(values, dict) or set(values) != set(
            AccumulationInventory.__dataclass_fields__
        ):
            raise ValueError("Invalid inventory")
        for key in (
            "quantity",
            "remaining_cost",
            "contributed_quote",
            "disposal_proceeds",
        ):
            if values[key] is not None:
                values[key] = canonical_decimal(values[key], positive=key == "quantity")
        if (
            type(values["pending_fee_reports"]) is not int
            or values["pending_fee_reports"] < 0
            or not isinstance(values["fees"], dict)
            or len(values["fees"]) > 32
        ):
            raise ValueError("Invalid fees")
        values["fees"] = {
            key: canonical_decimal(value) for key, value in values["fees"].items()
        }
        if (
            not isinstance(values["basis_provenance"], str)
            or len(values["basis_provenance"]) > 32
        ):
            raise ValueError("Invalid provenance")
        complete = (
            complete
            and values["basis_provenance"] == "exchange_fills"
            and values["pending_fee_reports"] == 0
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        raise AccumulationConflictError(
            "Inventory audit evidence is missing or inconsistent; restore a complete backup."
        ) from None
    totals = await model.AccumulationReturnTotals.get_or_none(
        activation=activation
    ).using_db(conn)
    if totals and (
        Decimal(totals.last_quantity) != Decimal(values["quantity"])
        or totals.last_cost != values["remaining_cost"]
    ):
        raise AccumulationConflictError(
            "Derived inventory and audit evidence disagree."
        )
    if (
        await model.AccumulationLifecycleOperation.filter(
            activation=activation, action="declare_ownership", status="applied"
        )
        .using_db(conn)
        .exists()
    ):
        complete = False
    return {"inventory": values, "deal_id": deal_id, "history_complete": complete}


class AccumulationInventoryRestore:
    """Reconstruct only a reviewed paused holding, never adopt arbitrary wallet coins."""

    def __init__(self, adapter: Any):
        self.adapter = adapter

    async def submit(self, payload: dict[str, Any]) -> Any:
        if (
            set(payload) != {"symbol", "action", "operation_id", "expected_revision"}
            or payload.get("action") != "restore_inventory"
            or not isinstance(payload["symbol"], str)
        ):
            raise AccumulationStateError("Invalid inventory restore request.")
        symbol = normalize_order_symbol(payload["symbol"])
        operation_id = validate_operation_id(payload["operation_id"])
        revision = payload["expected_revision"]
        if type(revision) is not int or not 0 <= revision < 2**63 - 1:
            raise AccumulationStateError("Invalid restore revision.")
        config = self.adapter.config()
        scope = await self.adapter.account_scope(config)
        request = json.dumps(
            {**payload, "symbol": symbol, "account_scope": scope}, sort_keys=True
        )

        async def snapshot(conn: Any) -> tuple[Any, Any, dict[str, Any]]:
            activation = await model.AccumulationActivation.get_or_none(
                symbol=symbol
            ).using_db(conn)
            if (
                activation is None
                or activation.account_scope != scope
                or activation.revision != revision
                or not activation.explicitly_paused
                or not activation.observations_initialized
                or activation.state not in {"paused", "blocked", "closing"}
            ):
                raise AccumulationConflictError(
                    "Restore requires current paused ownership in the configured account."
                )
            holding = await model.OpenTrades.get_or_none(symbol=symbol).using_db(conn)
            if holding is not None and (
                holding.lifecycle_mode != "accumulation"
                or activation.holding_id not in {None, holding.id}
            ):
                raise AccumulationConflictError(
                    "Conflicting managed holding requires investigation."
                )
            if holding is not None and activation.holding_id == holding.id:
                raise AccumulationConflictError("The holding is already linked.")
            if (
                await model.OpenTrades.filter(
                    symbol__startswith=symbol.split("/")[0] + "/"
                )
                .exclude(symbol=symbol)
                .using_db(conn)
                .exists()
            ):
                raise AccumulationConflictError(
                    "Shared base-asset ownership is ambiguous."
                )
            evidence = await _evidence(activation, conn)
            if (
                holding is not None
                and asdict(_inventory(holding)) != evidence["inventory"]
            ):
                raise AccumulationConflictError(
                    "The unlinked holding differs from audit evidence."
                )
            return activation, holding, evidence

        async def prior(conn: Any) -> Any:
            row = await model.AccumulationLifecycleOperation.get_or_none(
                operation_id=operation_id
            ).using_db(conn)
            if row is not None and row.request_json != request:
                raise AccumulationConflictError(
                    "Operation ID belongs to another request."
                )
            return row

        async with in_transaction() as conn:
            recorded = await prior(conn)
            if recorded is not None:
                return AccumulationCommandResult.from_operation(recorded)
            _, _, evidence = await snapshot(conn)
        async with asyncio.timeout(10):
            wallet = await self.adapter.account_inventory(symbol, config)
        if wallet.account_scope != scope or Decimal(
            canonical_decimal(wallet.free_base)
        ) < Decimal(evidence["inventory"]["quantity"]):
            raise AccumulationConflictError(
                "Fresh free wallet balance does not cover recorded inventory."
            )

        async def commit() -> Any:
            async with in_transaction() as conn:
                recorded = await prior(conn)
                if recorded is not None:
                    return AccumulationCommandResult.from_operation(recorded)
                activation, holding, current = await snapshot(conn)
                if (
                    current != evidence
                    or self.adapter.config() != config
                    or not 0 <= self.adapter.clock_ms() - wallet.observed_at_ms <= 10000
                ):
                    raise AccumulationConflictError(
                        "Inventory or account evidence changed; refresh first."
                    )
                values = evidence["inventory"]
                if holding is None:
                    holding = await model.OpenTrades.create(
                        using_db=conn,
                        symbol=symbol,
                        lifecycle_mode="accumulation",
                        deal_id=evidence["deal_id"],
                        execution_history_complete=evidence["history_complete"],
                        accumulation_net_quantity=values["quantity"],
                        accumulation_remaining_cost=values["remaining_cost"],
                        accumulation_contributed_quote=values["contributed_quote"],
                        accumulation_disposal_proceeds=values["disposal_proceeds"],
                        accumulation_fees_json=json.dumps(
                            {
                                "totals": values["fees"],
                                "pending_reports": values["pending_fee_reports"],
                            }
                        ),
                        accumulation_basis_provenance=values["basis_provenance"],
                        amount=float(values["quantity"]),
                        cost=float(values["remaining_cost"] or 0),
                    )
                previous_state = activation.state
                activation.holding = holding
                activation.state = (
                    "closing" if activation.state == "closing" else "paused"
                )
                await AccumulationAccountRebind._advance(activation, conn)
                activation.reason = "inventory_restored_paused"
                await activation.save(using_db=conn)
                row = await model.AccumulationLifecycleOperation.create(
                    using_db=conn,
                    activation=activation,
                    operation_id=operation_id,
                    action="restore_inventory",
                    request_json=request,
                    status="applied",
                    previous_state=previous_state,
                    previous_paused=True,
                    result_state=activation.state,
                    result_revision=activation.revision,
                    reason="inventory_restored_paused",
                )
                return AccumulationCommandResult.from_operation(row)

        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                raise AccumulationConflictError("Trading maintenance is active.")
            return await run_sqlite_write_with_retry(
                commit, "restoring recorded accumulation inventory"
            )
