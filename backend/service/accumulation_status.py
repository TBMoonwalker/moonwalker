"""Bounded, database-only dashboard projections for accumulation ownership."""

from __future__ import annotations

import json
from typing import Any

import model
from service.accumulation_commands import (
    CLOSE_ACTIONS,
    ENTRY_ACTIONS,
    RETIRABLE_ACTIONS,
    SALE_ACTIONS,
)
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_import import AccumulationImport
from service.accumulation_inventory_evidence import inventory_restore_required
from service.accumulation_ownership_evidence import recoverable_client_order_id
from service.accumulation_reporting import (
    accumulation_order_history,
    accumulation_portfolio,
)
from service.order_requests import normalize_order_symbol
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction


def _holding(row: model.OpenTrades | None) -> dict[str, Any] | None:
    if row is None:
        return None
    fees = None
    try:
        value = json.loads(row.accumulation_fees_json or "null")
        if (
            isinstance(value, dict)
            and set(value) == {"totals", "pending_reports"}
            and type(value["pending_reports"]) is int
            and value["pending_reports"] >= 0
            and isinstance(value["totals"], dict)
            and len(value["totals"]) <= 32
        ):
            fees = {
                "totals": {
                    key: canonical_decimal(amount)
                    for key, amount in value["totals"].items()
                },
                "pending_reports": value["pending_reports"],
            }
    except (ValueError, TypeError):
        pass  # Missing/corrupt fee evidence remains unknown, never zero fees.
    # NULL remains unknown. Never substitute legacy float mirrors or zero.
    return {
        "deal_id": row.deal_id,
        "net_quantity": row.accumulation_net_quantity,
        "remaining_cost": row.accumulation_remaining_cost,
        "contributed_quote": row.accumulation_contributed_quote,
        "disposal_proceeds": row.accumulation_disposal_proceeds,
        "basis_provenance": row.accumulation_basis_provenance,
        "execution_history_complete": row.execution_history_complete,
        "fees": fees,
    }


async def _summaries(
    rows: list[model.AccumulationActivation],
    connection: BaseDBAsyncClient,
    wait_reasons: dict[str, str],
    configured_account_scope: str | None = None,
) -> list[dict[str, Any]]:
    holdings = {
        row.id: row
        for row in await model.OpenTrades.filter(
            id__in=[item.holding_id for item in rows if item.holding_id is not None]
        ).using_db(connection)
    }
    versions = {
        row.id: row
        for row in await model.StrategyVersion.filter(
            id__in=[item.strategy_version_id for item in rows]
        ).using_db(connection)
    }
    result = []
    for row in rows:
        holding = holdings.get(row.holding_id)
        owned = holding is not None and (
            holding.symbol == row.symbol and holding.lifecycle_mode == "accumulation"
        )
        version = versions.get(row.strategy_version_id)
        result.append(
            {
                "activation_id": str(row.id),
                "account_matches": None
                if configured_account_scope is None
                else row.account_scope == configured_account_scope,
                "symbol": row.symbol,
                "state": row.state,
                "explicitly_paused": row.explicitly_paused,
                "revision": row.revision,
                "reason": row.reason,
                "runtime_wait_reason": wait_reasons.get(row.symbol),
                "observations_initialized": row.observations_initialized,
                "strategy_version_id": row.strategy_version_id,
                "strategy_slug": version.strategy_slug if version else None,
                "strategy_version": version.version if version else None,
                "inventory_restore_required": (
                    not owned and await inventory_restore_required(row, connection)
                ),
                "holding_integrity": (
                    "unlinked"
                    if row.holding_id is None
                    else "owned"
                    if owned
                    else "invalid"
                ),
                "holding": _holding(holding) if owned else None,
            }
        )
    return result


async def list_accumulation_status(
    *,
    limit: int = 50,
    after: str | None = None,
    wait_reasons: dict[str, str],
    configured_account_scope: str | None = None,
) -> dict[str, Any]:
    """Read one keyset page with a consistent inventory/version snapshot."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise AccumulationStateError("limit must be between 1 and 100.")
    query = model.AccumulationActivation.all().order_by("symbol")
    if after is not None:
        query = query.filter(symbol__gt=normalize_order_symbol(after))
    async with in_transaction() as connection:
        rows = await query.limit(limit + 1).using_db(connection)
        return {
            "activations": await _summaries(
                rows[:limit], connection, wait_reasons, configured_account_scope
            ),
            "next_after": rows[limit - 1].symbol if len(rows) > limit else None,
            "portfolio": await accumulation_portfolio(connection),
        }


def _operation(row: model.AccumulationLifecycleOperation) -> dict[str, Any]:
    result = {
        "operation_id": row.operation_id,
        "action": row.action,
        "status": row.status,
        "result_state": row.result_state,
        "result_revision": row.result_revision,
        "reason": row.reason,
        "target_version_id": row.target_version_id,
        "requested_quantity": row.requested_quantity,
        "created_at": row.created_at.isoformat(),
    }
    if row.action == "adjust_inventory" and row.status == "applied":
        try:
            request = json.loads(row.request_json)
            command = request["command"]
            result["adjustment"] = {
                "direction": command["direction"],
                "quantity": command["quantity"],
                "note": command["note"],
                **{
                    f"{when}_{name}": values[key]
                    for when, values in (
                        ("before", request["before"]["inventory"]),
                        ("after", request["after"]),
                    )
                    for name, key in (
                        ("quantity", "quantity"),
                        ("cost", "remaining_cost"),
                    )
                },
            }
        except (ValueError, TypeError, KeyError):
            pass  # A corrupt receipt is not an invitation to expose its raw request.
    return result


def _entry(
    row: model.AccumulationLifecycleOperation | None, symbol: str
) -> dict[str, Any] | None:
    if row is None:
        return None
    result = {
        **_operation(row),
        "source": None,
        "declaration": None,
        "declaration_invalid": False,
    }
    try:
        request = json.loads(row.request_json)
        if not isinstance(request, dict) or request.get("source") not in {
            "asap",
            "csv",
        }:
            raise AccumulationStateError("Invalid entry source.")
        result["source"] = request["source"]
        if request["source"] == "csv":
            value = request.get("imported_inventory")
            if not isinstance(value, dict):
                raise AccumulationStateError("Missing declaration.")
            declaration = AccumulationImport.from_dict(value)
            if declaration.symbol != symbol:
                raise AccumulationStateError("Declaration ownership mismatch.")
            result["declaration"] = {
                "net_quantity": declaration.quantity,
                "acquisition_cost": declaration.cost,
                "row_count": len(declaration.entries),
                "first_purchase_ms": declaration.entries[0][0],
                "historical_fees_known": False,
            }
    except (ValueError, TypeError, KeyError):
        result["declaration_invalid"] = True
    return result


async def get_accumulation_status(
    symbol: str,
    *,
    wait_reasons: dict[str, str],
    configured_account_scope: str | None = None,
) -> dict[str, Any] | None:
    """Read a current activation and bounded journal without exposing raw requests."""
    symbol = normalize_order_symbol(symbol)
    async with in_transaction() as connection:
        activation = await model.AccumulationActivation.get_or_none(
            symbol=symbol
        ).using_db(connection)
        if activation is None:
            return None
        result = (
            await _summaries(
                [activation], connection, wait_reasons, configured_account_scope
            )
        )[0]
        operations = (
            await model.AccumulationLifecycleOperation.filter(activation=activation)
            .using_db(connection)
            .order_by("-id")
            .limit(21)
        )
        entry = (
            await model.AccumulationLifecycleOperation.filter(
                activation=activation, action__in=ENTRY_ACTIONS | {"abandon_entry"}
            )
            .using_db(connection)
            .order_by("-id")
            .first()
        )
        close = (
            await model.AccumulationLifecycleOperation.filter(
                activation=activation,
                action__in=CLOSE_ACTIONS,
                result_revision=activation.revision,
                status__in=["pending", "reconciled", "cancelled"],
            )
            .using_db(connection)
            .order_by("-id")
            .first()
        )
        result.update(
            close_predecessor=_operation(close) if close is not None else None,
            entry=_entry(entry, symbol),
            operations=[_operation(row) for row in operations[:20]],
            older_operations_available=len(operations) > 20,
            portfolio=await accumulation_portfolio(connection),
            **await accumulation_order_history(activation, connection),
            quarantined_orders=[
                {
                    "placement_operation_id": row.operation_id,
                    "side": row.side,
                    "has_lookup_identity": bool(
                        row.exchange_order_id or recoverable_client_order_id(row)
                    ),
                }
                for row in await model.PlacementIntent.filter(
                    symbol=symbol, state__in=["quarantined", "restored_quarantined"]
                )
                .using_db(connection)
                .order_by("id")
                .limit(20)
            ],
            settled_commands=[
                _operation(row)
                for row in await model.AccumulationLifecycleOperation.filter(
                    activation=activation,
                    status="quarantined",
                    action__in=SALE_ACTIONS,
                    placement__state="completed",
                    placement__accumulation_checkpoint__terminal=True,
                    placement__accumulation_checkpoint__fees_complete=True,
                )
                .using_db(connection)
                .order_by("id")
                .limit(20)
            ],
            quarantined_commands=[
                _operation(row)
                for row in await model.AccumulationLifecycleOperation.filter(
                    activation=activation,
                    status="quarantined",
                    placement_id__isnull=True,
                    action__in=RETIRABLE_ACTIONS,
                )
                .using_db(connection)
                .order_by("id")
                .limit(20)
            ],
        )
        return result
