"""Explicit credential rotation proven by native order anchors and fresh inventory.

Wallet similarity is not account identity. CSV-only inventory and missing order
anchors are deliberately unsupported; this path never transfers or adopts coins.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any

import model
from service.accumulation_accounting import _inventory as validate_inventory
from service.accumulation_commands import (
    CLOSE_ACTIONS,
    RETIRABLE_ACTIONS,
    validate_operation_id,
)
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_fill import AccumulationFill
from service.accumulation_lifecycle import _require_settled, _result
from service.accumulation_order_fees import hydrate_accumulation_order
from service.accumulation_ownership_evidence import (
    native_client_identity,
    recorded_exchange_order_id,
    recoverable_client_order_id,
    retire_superseded_ownership_checks,
)
from service.accumulation_state import AccumulationConflictError
from service.database import run_sqlite_write_with_retry
from service.exchange_capabilities import ExchangeOrderLookupStatus
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.order_requests import normalize_order_symbol
from tortoise.transactions import in_transaction


def _anchor(row: Any) -> dict[str, Any]:
    placement = row.placement
    return {
        "checkpoint_id": row.id,
        "placement_id": placement.id,
        "exchange": placement.exchange_name,
        "order_id": recorded_exchange_order_id(row),
        "client_order_id": recoverable_client_order_id(placement),
        "native_client_identity": native_client_identity(placement),
        "symbol": placement.symbol,
        "side": placement.side,
        "filled": row.filled,
        "quote_cost": row.quote_cost,
        "fees": json.loads(row.fees_json),
        "terminal": row.terminal,
        "fees_complete": row.fees_complete,
        "placement_state": placement.state,
    }


def _inventory(holding: Any) -> dict[str, Any] | None:
    if holding is None:
        return None
    return {
        "id": holding.id,
        "deal_id": holding.deal_id,
        **{
            name: getattr(holding, name)
            for name in (
                "accumulation_net_quantity",
                "accumulation_remaining_cost",
                "accumulation_contributed_quote",
                "accumulation_disposal_proceeds",
                "accumulation_fees_json",
                "accumulation_basis_provenance",
                "execution_history_complete",
            )
        },
    }


async def _local_plan(
    activation: Any, config: dict[str, Any], conn: Any
) -> dict[str, Any]:
    await _require_settled(activation, conn)
    if (
        await model.AccumulationLifecycleOperation.filter(
            activation=activation,
            status__in=["pending", "quarantined"],
            action__in=RETIRABLE_ACTIONS,
        )
        .using_db(conn)
        .exists()
    ):
        raise AccumulationConflictError(
            "Original-account commands require reconciliation or retirement first."
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
            or not holding.execution_history_complete
            or holding.accumulation_basis_provenance
            not in {"exchange_fills", "unvalued_external_fees"}
        )
    ):
        raise AccumulationConflictError(
            "Only intact native accumulation ownership can be rebound; imported inventory requires separate repair."
        )
    quantity = (
        "0" if holding is None else canonical_decimal(holding.accumulation_net_quantity)
    )
    if holding is not None:
        if validate_inventory(holding).pending_fee_reports != 0:
            raise AccumulationConflictError(
                "Inventory fee evidence must be complete before account rebinding."
            )
    base = activation.symbol.split("/")[0]
    if (
        await model.OpenTrades.filter(symbol__startswith=base + "/")
        .exclude(symbol=activation.symbol)
        .using_db(conn)
        .exists()
    ):
        raise AccumulationConflictError(
            "Shared base-asset ownership requires separate repair."
        )
    checkpoints = model.AccumulationFillCheckpoint.filter(
        activation=activation
    ).using_db(conn)
    if (
        await checkpoints.filter(terminal=False).exists()
        or await checkpoints.filter(fees_complete=False).exists()
    ):
        raise AccumulationConflictError(
            "Order evidence must be complete before credential rotation."
        )
    filled = checkpoints.exclude(filled="0").select_related("placement")
    first, last = (
        await filled.order_by("id").first(),
        await filled.order_by("-id").first(),
    )
    if first is None:
        raise AccumulationConflictError(
            "Native historical order anchors are required; wallet similarity is not proof."
        )
    anchors = [_anchor(first)] + ([_anchor(last)] if last.id != first.id else [])
    for anchor in anchors:
        if (
            not anchor["order_id"]
            or not anchor["client_order_id"]
            or not anchor["native_client_identity"]
            or anchor["exchange"] != config["exchange"].lower()
            or anchor["symbol"] != activation.symbol
            or anchor["placement_state"] != "completed"
        ):
            raise AccumulationConflictError(
                "Same-venue completed orders with durable client identities are required."
            )
    return {
        "quantity": quantity,
        "holding": _inventory(holding),
        "anchors": anchors,
        "identity": {
            name: str(getattr(activation, name))
            for name in (
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


def _matches(anchor: dict[str, Any], order: dict[str, Any]) -> bool:
    report = AccumulationFill.from_order(order)

    def fees(values: dict[str, Any]) -> dict[str, Decimal]:
        return {
            currency: Decimal(canonical_decimal(value))
            for currency, value in values.items()
            if Decimal(canonical_decimal(value)) != 0
        }

    return (
        report.terminal
        and report.fees_complete
        and report.order_id == anchor["order_id"]
        and order.get("clientOrderId") == anchor["client_order_id"]
        and report.symbol == anchor["symbol"]
        and report.side == anchor["side"]
        and Decimal(report.filled) == Decimal(anchor["filled"])
        and Decimal(report.quote_cost) == Decimal(anchor["quote_cost"])
        and fees(report.fees) == fees(anchor["fees"])
    )


class AccumulationAccountRebind:
    """Rebind settled native ownership after explicit review; never enable buying."""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    async def submit(self, payload: dict[str, Any]) -> Any:
        if (
            not isinstance(payload, dict)
            or set(payload) != {"symbol", "action", "operation_id", "expected_revision"}
            or payload["action"] != "rebind_account"
        ):
            raise AccumulationStateError("Invalid account-rebinding request.")
        if not isinstance(payload["symbol"], str):
            raise AccumulationStateError("Invalid rebinding symbol.")
        symbol = normalize_order_symbol(payload["symbol"])
        operation_id = validate_operation_id(payload["operation_id"])
        revision = payload["expected_revision"]
        if type(revision) is not int or not 0 <= revision < 2**63 - 2:
            raise AccumulationStateError("Invalid account-rebinding revision.")
        command = {**payload, "symbol": symbol}
        config = self.adapter.config()
        scope = await self.adapter.account_scope(config)

        async def stage() -> Any:
            async with in_transaction() as conn:
                prior = await model.AccumulationLifecycleOperation.get_or_none(
                    operation_id=operation_id
                ).using_db(conn)
                if prior is not None:
                    request = json.loads(prior.request_json)
                    if (
                        request.get("command") != command
                        or request.get("new_account_scope") != scope
                    ):
                        raise AccumulationConflictError(
                            "Operation ID belongs to a different account-rebinding request."
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
                        "A changed credential scope and current holding revision are required."
                    )
                if activation.account_scope.startswith(
                    "credential-demo-v1:"
                ) != scope.startswith("credential-demo-v1:"):
                    raise AccumulationConflictError(
                        "Demo and live inventory cannot be rebound or declared across environments."
                    )
                plan = await _local_plan(activation, config, conn)
                previous_state, previous_paused = (
                    activation.state,
                    activation.explicitly_paused,
                )
                old_scope = activation.account_scope
                await self._advance(activation, conn)
                if activation.state not in {"closing", "stopped"}:
                    activation.state = "paused"
                activation.explicitly_paused = True
                activation.reason = "account_rebind_evidence_required"
                await activation.save(using_db=conn)
                return await model.AccumulationLifecycleOperation.create(
                    using_db=conn,
                    operation_id=operation_id,
                    activation=activation,
                    action="rebind_account",
                    request_json=json.dumps(
                        {
                            "command": command,
                            "old_account_scope": old_scope,
                            "new_account_scope": scope,
                            "plan": plan,
                        },
                        sort_keys=True,
                    ),
                    status="quarantined",
                    previous_state=previous_state,
                    previous_paused=previous_paused,
                    result_state=activation.state,
                    result_revision=activation.revision,
                    reason="account_rebind_evidence_required",
                )

        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                raise AccumulationConflictError("Trading maintenance is active.")
            journal = await run_sqlite_write_with_retry(
                stage, "staging account rebinding"
            )
        if journal.status == "applied":
            return _result(journal)
        if journal.status != "quarantined":
            raise AccumulationConflictError(
                "Account-rebinding request is no longer active."
            )
        request = json.loads(journal.request_json)
        async with asyncio.timeout(30):
            for anchor in request["plan"]["anchors"]:
                lookup = await self.adapter.exchange.lookup_spot_order(
                    symbol,
                    config,
                    exchange_order_id=anchor["order_id"],
                    client_order_id=anchor["client_order_id"],
                )
                if (
                    lookup.status != ExchangeOrderLookupStatus.FOUND
                    or lookup.order is None
                ):
                    return _result(journal)
                hydrated = await hydrate_accumulation_order(
                    self.adapter.exchange, lookup.order, config
                )
                if not _matches(anchor, hydrated):
                    raise AccumulationConflictError(
                        "Historical order evidence does not match the original account."
                    )
            wallet = await self.adapter.account_inventory(symbol, config)
        if wallet.account_scope != scope or Decimal(
            canonical_decimal(wallet.free_base)
        ) < Decimal(request["plan"]["quantity"]):
            raise AccumulationConflictError(
                "The configured account does not cover the managed inventory."
            )

        async def commit() -> Any:
            async with in_transaction() as conn:
                current = await model.AccumulationLifecycleOperation.get(
                    operation_id=operation_id
                ).using_db(conn)
                if current.status == "applied":
                    return _result(current)
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
                    or await _local_plan(activation, config, conn) != request["plan"]
                ):
                    raise AccumulationConflictError(
                        "Ownership, credentials or evidence changed during account rebinding."
                    )
                activation.account_scope = scope
                await self._advance(activation, conn)
                activation.reason = "account_rebound_paused"
                await activation.save(using_db=conn)
                await retire_superseded_ownership_checks(activation, current, conn)
                current.status, current.reason = "applied", "account_rebound_paused"
                current.result_state, current.result_revision = (
                    activation.state,
                    activation.revision,
                )
                await current.save(using_db=conn)
                return _result(current)

        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                raise AccumulationConflictError("Trading maintenance is active.")
            return await run_sqlite_write_with_retry(
                commit, "committing account rebinding"
            )

    @staticmethod
    async def _advance(activation: Any, conn: Any) -> None:
        await (
            model.AccumulationLifecycleOperation.filter(
                activation=activation,
                action__in=CLOSE_ACTIONS,
                status__in=["reconciled", "cancelled"],
                result_revision=activation.revision,
            )
            .using_db(conn)
            .update(result_revision=activation.revision + 1)
        )
        activation.revision += 1
