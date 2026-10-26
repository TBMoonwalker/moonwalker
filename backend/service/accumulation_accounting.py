"""Atomic accumulation inventory, execution journal and opportunity consumption.

This is a persistence boundary for already accepted exchange orders, not order
admission. The caller must verify the active account before supplying evidence.
No database transaction or symbol lock is held over exchange network I/O.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

import model
from service.accumulation_commands import CLOSE_ACTIONS, SALE_ACTIONS
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_fill import (
    AccumulationFill,
    AccumulationInventory,
    apply_fill_delta,
)
from service.accumulation_notifications import accumulation_input_notifications
from service.accumulation_ownership_evidence import (
    native_client_identity,
    recoverable_client_order_id,
    retire_superseded_ownership_checks,
)
from service.accumulation_return_totals import record_return_delta
from service.accumulation_strategy import SUPPORTED_TIMEFRAMES
from service.database import run_sqlite_write_with_retry
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.placement_intents import deserialize_placement_payload
from service.placement_workflow import PlacementWorkflow
from tortoise.transactions import in_transaction


@dataclass(frozen=True)
class AccumulationAccountingResult:
    """Persistence outcome; terminal exchange status alone is not settlement."""

    operation_id: str
    settled: bool
    consumed: bool
    inventory: dict[str, Any] | None


def _fee_identity(fees: dict[str, str]) -> dict[str, Decimal]:
    """Compare economic fee totals independently of spelling and zero entries."""
    return {
        currency: Decimal(value)
        for currency, value in fees.items()
        if Decimal(value) != 0
    }


def _inventory(holding: model.OpenTrades | None) -> AccumulationInventory:
    if holding is None:
        return AccumulationInventory("0", "0", "0", "0", {})
    fees = json.loads(holding.accumulation_fees_json or "null")
    if not isinstance(fees, dict) or set(fees) != {"totals", "pending_reports"}:
        raise AccumulationStateError("Missing or corrupt accumulation fee totals.")
    if type(fees["pending_reports"]) is not int or fees["pending_reports"] < 0:
        raise AccumulationStateError("Invalid pending fee count.")
    if not isinstance(fees["totals"], dict) or len(fees["totals"]) > 32:
        raise AccumulationStateError("Invalid fee currency totals.")
    return AccumulationInventory(
        canonical_decimal(holding.accumulation_net_quantity),
        canonical_decimal(holding.accumulation_remaining_cost)
        if holding.accumulation_remaining_cost is not None
        else None,
        canonical_decimal(holding.accumulation_contributed_quote)
        if holding.accumulation_contributed_quote is not None
        else None,
        canonical_decimal(holding.accumulation_disposal_proceeds),
        {key: canonical_decimal(value) for key, value in fees["totals"].items()},
        fees["pending_reports"],
        holding.accumulation_basis_provenance or "unknown",
    )


async def _binding(placement: model.PlacementIntent, conn: Any) -> tuple[Any, Any, Any]:
    attempt = await model.AccumulationAttempt.get_or_none(placement=placement).using_db(
        conn
    )
    operation = await model.AccumulationLifecycleOperation.get_or_none(
        placement=placement
    ).using_db(conn)
    if (attempt is None) == (operation is None):
        raise AccumulationStateError("Placement needs exactly one accumulation owner.")
    opportunity = (
        await model.AccumulationOpportunity.get(id=attempt.opportunity_id).using_db(
            conn
        )
        if attempt
        else None
    )
    activation = await model.AccumulationActivation.get(
        id=opportunity.activation_id if opportunity else operation.activation_id
    ).using_db(conn)
    if opportunity:
        if placement.side != "buy" or placement.action != "buy":
            raise AccumulationStateError("Opportunity placement must be a buy.")
        if opportunity.generation != activation.generation:
            raise AccumulationStateError("Opportunity belongs to another generation.")
    else:
        if (
            placement.side != "sell"
            or placement.action != "sell"
            or operation.action not in SALE_ACTIONS
        ):
            raise AccumulationStateError(
                "Only explicit manual sale intent can dispose inventory."
            )
        request = json.loads(placement.request_json)
        if (
            not isinstance(request, dict)
            or request.get("accumulation_operation_id") != operation.operation_id
            or request.get("accumulation_action") != operation.action
        ):
            raise AccumulationStateError(
                "Manual-sale placement context does not match."
            )
    return activation, opportunity, operation


async def persist_accumulation_order(
    operation_id: str,
    order: dict[str, Any],
    *,
    account_scope: str,
    exchange_name: str,
    repair_operation_id: str | None = None,
) -> AccumulationAccountingResult:
    """Apply cumulative exchange evidence exactly once under the symbol lock.

    Late fills are accounted even while paused, closing or expired. Settlement
    requires explicit terminal status and complete fee evidence. Unknown outcomes
    have no synthetic report and leave the existing commitment untouched.
    """
    report = AccumulationFill.from_order(order)

    async def persist() -> tuple[AccumulationAccountingResult, bool]:
        async with in_transaction() as conn:
            placement = await model.PlacementIntent.get_or_none(
                operation_id=operation_id
            ).using_db(conn)
            if placement is None:
                raise AccumulationStateError("Placement identity was not found.")
            activation, opportunity, operation = await _binding(placement, conn)
            repair = None
            if repair_operation_id is not None:
                repair = await model.AccumulationLifecycleOperation.get_or_none(
                    operation_id=repair_operation_id
                ).using_db(conn)
                if repair is None or repair.action != "repair_order":
                    raise AccumulationStateError(
                        "Explicit repair authorization is missing."
                    )
                request = json.loads(repair.request_json)
                if (
                    repair.activation_id != activation.id
                    or request.get("placement_operation_id") != operation_id
                    or request.get("account_scope") != account_scope
                ):
                    raise AccumulationStateError("Repair ownership does not match.")
                if repair.status == "applied":
                    return (
                        AccumulationAccountingResult(operation_id, True, False, None),
                        False,
                    )
                if (
                    repair.status != "quarantined"
                    or repair.result_revision != activation.revision
                    or not activation.explicitly_paused
                    or placement.state not in {"quarantined", "restored_quarantined"}
                    or not report.terminal
                    or not report.fees_complete
                    or operation is not None
                    and operation.status != "quarantined"
                ):
                    raise AccumulationStateError(
                        "Repair requires unchanged paused quarantine and complete terminal evidence."
                    )
                if operation is not None and json.loads(placement.request_json).get(
                    "generation"
                ) != str(activation.generation):
                    raise AccumulationStateError(
                        "Sale repair belongs to another generation."
                    )
                client_id = recoverable_client_order_id(placement)
                if activation.account_scope != account_scope:
                    if (
                        not native_client_identity(placement)
                        or order.get("clientOrderId") != client_id
                    ):
                        raise AccumulationStateError(
                            "Changed credentials did not prove the original private client order identity."
                        )
                    activation.account_scope = account_scope
                if (
                    not placement.client_order_id
                    and client_id
                    and order.get("clientOrderId") == client_id
                ):
                    placement.client_order_id = client_id
            if (
                activation.account_scope != account_scope
                or placement.exchange_name != exchange_name
            ):
                raise AccumulationStateError("Account or exchange identity changed.")
            if placement.exchange_order_id is None:
                if (
                    not placement.client_order_id
                    or order.get("clientOrderId") != placement.client_order_id
                ):
                    raise AccumulationStateError(
                        "Lookup did not confirm the submitted client identity."
                    )
                placement.exchange_order_id = report.order_id
            if (
                placement.symbol != report.symbol
                or activation.symbol != report.symbol
                or placement.side != report.side
                or placement.exchange_order_id != report.order_id
            ):
                raise AccumulationStateError(
                    "Exchange evidence belongs to another order."
                )
            checkpoint = await model.AccumulationFillCheckpoint.get_or_none(
                placement=placement
            ).using_db(conn)
            if checkpoint and checkpoint.activation_id != activation.id:
                raise AccumulationStateError("Checkpoint ownership is inconsistent.")
            if checkpoint and (
                Decimal(checkpoint.filled) == Decimal(report.filled)
                and Decimal(checkpoint.quote_cost) == Decimal(report.quote_cost)
                and _fee_identity(json.loads(checkpoint.fees_json))
                == _fee_identity(report.fees)
                and checkpoint.terminal == report.terminal
                and checkpoint.fees_complete == report.fees_complete
            ):
                if repair is not None:
                    activation.revision += 1
                    await _finish_repair(repair, activation, placement, operation, conn)
                return (
                    AccumulationAccountingResult(
                        operation_id,
                        checkpoint.terminal and checkpoint.fees_complete,
                        bool(opportunity and opportunity.consumed_at),
                        json.loads(checkpoint.inventory_json)
                        if checkpoint.inventory_json
                        else None,
                    ),
                    False,
                )
            if repair is None and placement.state not in {
                "submitting",
                "accepted",
                "indeterminate",
                "reconciling",
                "filled",
            }:
                raise AccumulationStateError(
                    "Placement requires repair before further accounting."
                )
            if checkpoint and checkpoint.terminal and not report.terminal:
                raise AccumulationStateError(
                    "Terminal order evidence cannot become open."
                )
            if checkpoint and checkpoint.fees_complete and not report.fees_complete:
                raise AccumulationStateError(
                    "Complete fee evidence cannot become unknown."
                )
            if opportunity and opportunity.unresolved_slot != activation.id:
                raise AccumulationStateError(
                    "Opportunity no longer owns the unresolved slot."
                )
            if operation and operation.status != "pending" and repair is None:
                raise AccumulationStateError(
                    "Manual-sale operation is no longer pending."
                )
            holding = await model.OpenTrades.get_or_none(symbol=report.symbol).using_db(
                conn
            )
            if holding is not None and (
                holding.id != activation.holding_id
                or holding.lifecycle_mode != "accumulation"
            ):
                raise AccumulationStateError(
                    "Holding ownership conflicts with this activation."
                )
            if holding is None and (
                activation.holding_id is not None
                or checkpoint
                and checkpoint.deal_id
                or report.side == "sell"
            ):
                raise AccumulationStateError("Owned accumulation inventory is missing.")
            previous_filled = checkpoint.filled if checkpoint else "0"
            previous_cost = checkpoint.quote_cost if checkpoint else "0"
            previous_fees = json.loads(checkpoint.fees_json) if checkpoint else {}
            inventory, delta = apply_fill_delta(
                _inventory(holding),
                report,
                previous_filled=previous_filled,
                previous_cost=previous_cost,
                previous_fees=previous_fees,
                previously_incomplete=bool(
                    checkpoint
                    and Decimal(checkpoint.filled) > 0
                    and not checkpoint.fees_complete
                ),
            )
            now = datetime.now(timezone.utc)
            consumed_now = bool(
                opportunity
                and Decimal(report.filled) > 0
                and opportunity.consumed_at is None
            )
            if consumed_now:
                if opportunity.is_initial_entry and activation.consumption_revision:
                    # Repair already-reactivated cycles created before generation
                    # guards reset. The first owned fill proves this cycle started;
                    # invalidate observations derived from the preceding holding.
                    activation.consumption_revision = 0
                    activation.execution_guard_json = None
                    activation.observation_epoch += 1
                    activation.observations_initialized = False
                    # Retain the validated timestamp as the rebase floor. A null
                    # baseline would make the strict decision identity unreadable.
                if not opportunity.is_initial_entry:
                    activation.consumption_revision += 1
                    activation.execution_guard_json = json.dumps(
                        {
                            "opportunity_id": str(opportunity.id),
                            "signal_close_ms": opportunity.signal_close_ms,
                            "signal_price": canonical_decimal(
                                opportunity.signal_price, positive=True
                            ),
                            "signal_atr": canonical_decimal(
                                opportunity.signal_atr, positive=True
                            ),
                            "strategy_version_id": opportunity.strategy_version_id,
                            "consumption_revision": activation.consumption_revision,
                        },
                        sort_keys=True,
                    )
                opportunity.consumed_at = now
                opportunity.consumption_revision = activation.consumption_revision
            changed = (
                Decimal(delta["filled"]) != 0
                or Decimal(delta["quote_cost"]) != 0
                or any(Decimal(value) for value in delta["fees"].values())
            )
            settled = report.terminal and report.fees_complete
            if Decimal(report.filled) > 0:
                if holding is None:
                    holding = await model.OpenTrades.create(
                        using_db=conn,
                        symbol=report.symbol,
                        deal_id=str(uuid4()),
                        lifecycle_mode="accumulation",
                        open_date=datetime.fromtimestamp(
                            report.timestamp_ms / 1000, timezone.utc
                        ).isoformat(),
                    )
                    activation.holding_id = holding.id
                holding.accumulation_net_quantity = inventory.quantity
                holding.accumulation_remaining_cost = inventory.remaining_cost
                holding.accumulation_contributed_quote = inventory.contributed_quote
                holding.accumulation_disposal_proceeds = inventory.disposal_proceeds
                holding.accumulation_fees_json = json.dumps(
                    {
                        "totals": inventory.fees,
                        "pending_reports": inventory.pending_fee_reports,
                    },
                    sort_keys=True,
                )
                holding.accumulation_basis_provenance = inventory.basis_provenance
                # Legacy display mirrors are never inputs to accumulation accounting.
                holding.amount = float(inventory.quantity)
                holding.cost = (
                    float(inventory.remaining_cost)
                    if inventory.remaining_cost is not None
                    else 0.0
                )
                holding.avg_price = (
                    holding.cost / holding.amount if holding.amount else 0.0
                )
                await holding.save(using_db=conn)
                if changed:
                    version = await model.StrategyVersion.get(
                        id=opportunity.strategy_version_id
                        if opportunity
                        else activation.strategy_version_id
                    ).using_db(conn)
                    request = deserialize_placement_payload(placement.request_json)
                    metadata = deserialize_placement_payload(
                        request.get("metadata_json")
                    )
                    stored_policy = metadata.get("accumulation")
                    policy = {
                        key: value
                        for key, value in (
                            stored_policy.items()
                            if isinstance(stored_policy, dict)
                            else ()
                        )
                        if key in {"timeframe", "sizing_policy"}
                        and isinstance(value, str)
                        and len(value) <= 64
                    }
                    if policy.get("timeframe") not in SUPPORTED_TIMEFRAMES:
                        policy.pop("timeframe", None)
                    await model.TradeExecutions.create(
                        using_db=conn,
                        deal_id=holding.deal_id,
                        symbol=report.symbol,
                        side=report.side,
                        role="accumulation_buy" if opportunity else "accumulation_sell",
                        timestamp=str(report.timestamp_ms),
                        price=float(
                            Decimal(report.quote_cost) / Decimal(report.filled)
                        ),
                        amount=float(delta["filled"]),
                        ordersize=float(delta["quote_cost"]),
                        fee=0.0,
                        order_id=report.order_id,
                        order_type=placement.order_type,
                        strategy_slug=version.strategy_slug,
                        strategy_version=version.version,
                        timeframe=policy.get("timeframe"),
                        metadata_json=json.dumps(
                            {
                                "accumulation": {
                                    **policy,
                                    "operation_id": operation_id,
                                    "initial_entry": bool(
                                        opportunity and opportunity.is_initial_entry
                                    ),
                                    "delta": delta,
                                    "inventory": json.loads(inventory.serialize()),
                                    "fees_complete": report.fees_complete,
                                }
                            },
                            sort_keys=True,
                        ),
                    )
            if opportunity:
                opportunity.status = (
                    "consumed" if opportunity.consumed_at else "unresolved"
                )
                if settled:
                    opportunity.unresolved_slot = None
                    if not opportunity.consumed_at:
                        opportunity.status = (
                            "retryable"
                            if int(now.timestamp() * 1000) < opportunity.expires_at_ms
                            else "expired"
                        )
                        opportunity.next_retry_at = now + timedelta(
                            seconds=min(30, 2 ** min(opportunity.retry_index, 5))
                        )
                        opportunity.retry_index += 1
                await opportunity.save(using_db=conn)
            await record_return_delta(
                activation,
                inventory,
                delta,
                side=report.side,
                timestamp_ms=report.timestamp_ms,
                connection=conn,
            )
            await model.AccumulationFillCheckpoint.update_or_create(
                using_db=conn,
                placement=placement,
                defaults={
                    "activation": activation,
                    "deal_id": holding.deal_id if holding else None,
                    "filled": report.filled,
                    "quote_cost": report.quote_cost,
                    "fees_json": json.dumps(report.fees, sort_keys=True),
                    "fees_complete": report.fees_complete,
                    "terminal": report.terminal,
                    "evidence_json": report.serialize(),
                    "inventory_json": inventory.serialize() if holding else None,
                },
            )
            if (
                settled
                and operation
                and operation.action in CLOSE_ACTIONS
                and Decimal(inventory.quantity) == 0
                and inventory.pending_fee_reports == 0
            ):
                await holding.delete(using_db=conn)
                activation.holding_id = None
            activation.revision += 1
            await activation.save(using_db=conn)
            # Fill accounting is expected progress within a pending command, not
            # a competing operator edit. Keep its completion revision current.
            await (
                model.AccumulationLifecycleOperation.filter(
                    activation=activation, status="pending"
                )
                .using_db(conn)
                .update(result_revision=activation.revision)
            )
            placement.state = "persisted" if settled else "accepted"
            placement.result_json = json.dumps(order, sort_keys=True, default=str)
            await placement.save(using_db=conn)
            if repair is not None:
                await _finish_repair(repair, activation, placement, operation, conn)
            return (
                AccumulationAccountingResult(
                    operation_id,
                    settled,
                    bool(opportunity and opportunity.consumed_at),
                    json.loads(inventory.serialize()) if holding else None,
                ),
                True,
            )

    async with lifecycle_mutation_coordinator.mutation(report.symbol) as admitted:
        if not admitted:
            raise AccumulationStateError("Accounting is paused during maintenance.")
        result, accounting_changed = await run_sqlite_write_with_retry(
            persist, "persisting accumulation fill"
        )
    if accounting_changed:
        PlacementWorkflow.log_persisted(
            operation_id,
            symbol=report.symbol,
            side=report.side,
            order_id=report.order_id,
            amount=report.filled,
            quote_cost=report.quote_cost,
        )
    accumulation_input_notifications.publish()
    return result


async def _finish_repair(
    repair: Any, activation: Any, placement: Any, operation: Any, conn: Any
) -> None:
    """Complete only reconciliation; preserve pause and any remaining close latch."""
    placement.state = "completed"
    placement.reason_code = "explicit_restore_reconciliation"
    await placement.save(using_db=conn)
    activation.explicitly_paused = True
    activation.reason = "restore_reconciled_paused"
    if operation is not None:
        operation.status = (
            "reconciled" if operation.action in CLOSE_ACTIONS else "applied"
        )
        operation.reason = "restore_reconciled_no_replay"
        if operation.action not in CLOSE_ACTIONS:
            activation.state = "paused"
        operation.result_revision = activation.revision
        operation.result_state = activation.state
        await operation.save(using_db=conn)
    if (
        activation.state == "closing"
        and activation.holding_id is None
        and not await model.PlacementIntent.filter(symbol=activation.symbol)
        .exclude(state__in=["completed", "rejected"])
        .using_db(conn)
        .exists()
    ):
        activation.state = "stopped"
        if operation is not None:
            operation.status = "applied"
            operation.result_state = "stopped"
            await operation.save(using_db=conn)
    await activation.save(using_db=conn)
    await retire_superseded_ownership_checks(activation, repair, conn)
    repair.status = "applied"
    repair.reason = "terminal_evidence_accounted"
    repair.result_state = activation.state
    repair.result_revision = activation.revision
    await repair.save(using_db=conn)


async def reject_unsubmitted_accumulation_order(
    operation_id: str,
    *,
    account_scope: str,
    exchange_name: str,
    reason_code: str = "startup_confirmed_never_submitted",
) -> str:
    """Release a prepared attempt only with durable proof it was never submitted."""
    placement = await model.PlacementIntent.get(operation_id=operation_id)

    async def persist() -> str:
        async with in_transaction() as conn:
            placement = await model.PlacementIntent.get(
                operation_id=operation_id
            ).using_db(conn)
            activation, opportunity, _ = await _binding(placement, conn)
            if (
                activation.account_scope != account_scope
                or placement.exchange_name != exchange_name
            ):
                raise AccumulationStateError("Account or exchange identity changed.")
            if (
                placement.state != "prepared"
                or placement.submitted_at is not None
                or placement.exchange_order_id is not None
            ):
                raise AccumulationStateError(
                    "Placement may have been submitted; reconcile it."
                )
            if (
                await model.AccumulationFillCheckpoint.filter(placement=placement)
                .using_db(conn)
                .exists()
            ):
                raise AccumulationStateError(
                    "Unsubmitted placement has accounting evidence."
                )
            if opportunity:
                if (
                    opportunity.consumed_at is not None
                    or opportunity.unresolved_slot != activation.id
                ):
                    raise AccumulationStateError(
                        "Unsubmitted opportunity has inconsistent ownership."
                    )
                opportunity.unresolved_slot = None
                now = datetime.now(timezone.utc)
                opportunity.status = (
                    "retryable"
                    if int(now.timestamp() * 1000) < opportunity.expires_at_ms
                    else "expired"
                )
                opportunity.next_retry_at = now + timedelta(
                    seconds=min(30, 2 ** min(opportunity.retry_index, 5))
                )
                opportunity.retry_index += 1
                await opportunity.save(using_db=conn)
            placement.state = "rejected"
            placement.reason_code = reason_code
            placement.completed_at = datetime.now(timezone.utc)
            await placement.save(using_db=conn)
            return "rejected"

    async with lifecycle_mutation_coordinator.mutation(placement.symbol) as admitted:
        if not admitted:
            raise AccumulationStateError("Accounting is paused during maintenance.")
        return await run_sqlite_write_with_retry(
            persist, "rejecting unsubmitted accumulation attempt"
        )
