"""Single-submission execution of durably reserved accumulation buys.

The accumulation runtime invokes this worker for buys only; a caller cannot
turn this interface into an automatic sell. Raw cumulative order
reports flow through the dedicated accumulation accounting boundary.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import ccxt.async_support as ccxt
import helper
import model
from service.accumulation_accounting import (
    persist_accumulation_order,
    reject_unsubmitted_accumulation_order,
)
from service.accumulation_budget import usable_accumulation_quote
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_exchange import (
    AccumulationBuyPrecision,
    AccumulationExchangeAdapter,
    preflight_accumulation_precision,
)
from service.accumulation_portfolio import AccumulationAdmissionInputs
from service.accumulation_strategy import (
    SIZING_POLICY,
    AccumulationParameters,
    effective_accumulation_parameters,
)
from service.capital_budget import CapitalBudgetService
from service.database import run_sqlite_write_with_retry
from service.delisting_protection import DelistingProtectionService
from service.exchange_capabilities import ExchangeSubmissionIndeterminate
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.placement_intents import (
    PlacementIntentService,
    PlacementIntentState,
    deserialize_placement_payload,
)
from service.placement_workflow import PlacementWorkflow
from service.trading_controls import is_global_trading_paused
from service.trading_maintenance import trading_maintenance_barrier
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger(
    "logs/accumulation_execution.log", "accumulation_execution"
)


@dataclass(frozen=True)
class AccumulationExecutionResult:
    """Journal state after one execution attempt, without implying a full fill."""

    operation_id: str
    state: str
    reason: str


class AccumulationBuyExecutor:
    """Preflight, claim once, submit once and account; never retry a wire effect."""

    def __init__(self, adapter: AccumulationExchangeAdapter) -> None:
        self.adapter = adapter
        self.intents = PlacementIntentService()
        self.delisting_protection = DelistingProtectionService.shared()

    async def _claim(
        self,
        operation_id: str,
        config: dict[str, Any],
        inputs: AccumulationAdmissionInputs,
        precision: AccumulationBuyPrecision,
    ) -> str:
        async def persist() -> str:
            async with in_transaction() as conn:
                if is_global_trading_paused(config):
                    return "WAIT_GLOBAL_PAUSE"
                if config.get("trade_mode") != "accumulation":
                    return "WAIT_STATE"
                if config != self.adapter.config():
                    return "WAIT_STATE"
                row = await model.PlacementIntent.get(
                    operation_id=operation_id
                ).using_db(conn)
                if row.state != "prepared":
                    return str(row.state)
                attempt = await model.AccumulationAttempt.get_or_none(
                    placement_id=row.id
                ).using_db(conn)
                if attempt is None:
                    raise AccumulationStateError(
                        "Only an owned accumulation buy may submit."
                    )
                opportunity = await model.AccumulationOpportunity.get(
                    id=attempt.opportunity_id
                ).using_db(conn)
                activation = await model.AccumulationActivation.get(
                    id=opportunity.activation_id
                ).using_db(conn)
                request = deserialize_placement_payload(row.request_json)
                metadata = json.loads(request.get("metadata_json") or "{}")
                identity = metadata.get("accumulation", {})
                now = self.adapter.clock_ms()
                if (
                    row.side != "buy"
                    or row.action != "buy"
                    or row.order_type != "limit"
                    or activation.symbol != row.symbol
                    or activation.account_scope != inputs.funding.account_scope
                    or row.exchange_name != inputs.funding.exchange_name
                    or identity.get("opportunity_id") != str(opportunity.id)
                    or identity.get("admitted_revision") != activation.revision
                    or identity.get("consumption_revision")
                    != activation.consumption_revision
                    or identity.get("generation") != str(activation.generation)
                    or identity.get("observation_epoch") != activation.observation_epoch
                    or identity.get("strategy_version_id")
                    != activation.strategy_version_id
                    or opportunity.strategy_version_id != activation.strategy_version_id
                    or opportunity.generation != activation.generation
                    or opportunity.observation_epoch != activation.observation_epoch
                    or opportunity.unresolved_slot != activation.id
                    or opportunity.consumed_at is not None
                    or activation.state != "enabled"
                    or activation.explicitly_paused
                ):
                    return "WAIT_STATE"
                if not opportunity.is_initial_entry and (
                    identity.get("sizing_policy") != SIZING_POLICY
                    or identity.get("timeframe")
                    != effective_accumulation_parameters(
                        AccumulationParameters(), config.get("timeframe")
                    ).timeframe
                ):
                    return "WAIT_STATE"
                if now >= opportunity.expires_at_ms:
                    return "WAIT_EXPIRED"
                if (
                    not 0 <= now - inputs.quote_timestamp_ms <= 10000
                    or Decimal(inputs.ask_price) > Decimal(precision.limit_price)
                    or Decimal(precision.limit_price)
                    > Decimal(opportunity.signal_price)
                    or Decimal(precision.requested_quote)
                    != Decimal(canonical_decimal(request.get("ordersize")))
                ):
                    return "WAIT_PRICE"
                usable = await usable_accumulation_quote(
                    config,
                    inputs.funding,
                    now_ms=now,
                    exclude_operation_id=operation_id,
                )
                if usable is None or Decimal(usable) < Decimal(
                    precision.requested_quote
                ):
                    return "WAIT_BUDGET"
                if config != self.adapter.config():
                    return "WAIT_STATE"
                decision = self.delisting_protection.evaluate_cached_buy(
                    row.symbol, config
                )
                if not decision.allowed:
                    return decision.reason_code or "blocked_delisting_check_unavailable"
                request["amount"] = precision.amount
                request["limit_price"] = precision.limit_price
                identity["executable_quote"] = precision.executable_quote
                identity["precision_checked_at_ms"] = now
                request["metadata_json"] = json.dumps(metadata, sort_keys=True)
                row.request_json = json.dumps(request, sort_keys=True)
                row.requested_amount = float(precision.amount)
                row.state = "submitting"
                row.submitted_at = datetime.fromtimestamp(now / 1000, timezone.utc)
                await row.save(using_db=conn)
                return "claimed"

        async with CapitalBudgetService.reservation_guard():
            return await run_sqlite_write_with_retry(
                persist, "claiming accumulation submission"
            )

    async def _reject_prepared(
        self, operation_id: str, config: dict[str, Any], reason: str
    ) -> AccumulationExecutionResult:
        row = await self.intents.get(operation_id)
        if row.state != "prepared":
            return AccumulationExecutionResult(
                operation_id, str(row.state), "ALREADY_CLAIMED"
            )
        try:
            state = await reject_unsubmitted_accumulation_order(
                operation_id,
                account_scope=await self.adapter.account_scope(config),
                exchange_name=config["exchange"],
                reason_code=reason,
            )
        except AccumulationStateError:
            # Another worker may have claimed the intent after the preflight failed.
            latest = await self.intents.get(operation_id)
            if latest.state == "prepared":
                raise
            return AccumulationExecutionResult(
                operation_id, str(latest.state), "ALREADY_CLAIMED"
            )
        return AccumulationExecutionResult(operation_id, state, reason)

    async def execute(self, operation_id: str) -> AccumulationExecutionResult:
        """Execute one owned prepared buy; subsequent calls only report its state."""
        async with trading_maintenance_barrier.operation() as admitted:
            if not admitted:
                return AccumulationExecutionResult(
                    operation_id, "prepared", "WAIT_MAINTENANCE"
                )
            return await self._execute(operation_id)

    async def _execute(self, operation_id: str) -> AccumulationExecutionResult:
        row = await self.intents.get(operation_id)
        if row is None:
            raise AccumulationStateError("Placement does not exist.")
        if row.state != "prepared":
            return AccumulationExecutionResult(
                operation_id, str(row.state), "ALREADY_CLAIMED"
            )
        if (
            row.action != "buy"
            or not await model.AccumulationAttempt.filter(placement_id=row.id).exists()
        ):
            raise AccumulationStateError("Only an owned accumulation buy may submit.")
        config = self.adapter.config()
        request = deserialize_placement_payload(row.request_json)
        activation = await model.AccumulationActivation.get_or_none(symbol=row.symbol)
        if (
            activation is None
            or activation.account_scope != await self.adapter.account_scope(config)
            or row.exchange_name != config["exchange"]
        ):
            return AccumulationExecutionResult(operation_id, "prepared", "WAIT_ACCOUNT")
        # No lifecycle or portfolio lock is held across authenticated preflight reads.
        try:
            inputs = await self.adapter.read_inputs(row.symbol, config)
        except (AccumulationStateError, ccxt.BaseError, TimeoutError, OSError):
            latest = await self.intents.get(operation_id)
            return AccumulationExecutionResult(
                operation_id,
                str(latest.state),
                "WAIT_DATA" if latest.state == "prepared" else "ALREADY_CLAIMED",
            )
        try:
            ceiling = await self.adapter.exchange.get_spot_buy_ceiling(
                row.symbol,
                canonical_decimal(request.get("maximum_buy_price"), positive=True),
                config,
            )
            precision = preflight_accumulation_precision(
                self.adapter.exchange.exchange,
                row.symbol,
                canonical_decimal(request.get("ordersize"), positive=True),
                ceiling,
            )
        except (AccumulationStateError, ccxt.InvalidOrder):
            return await self._reject_prepared(operation_id, config, "WAIT_PRECISION")
        except (ccxt.BaseError, TimeoutError, OSError, ValueError):
            return AccumulationExecutionResult(operation_id, "prepared", "WAIT_DATA")

        try:
            decision = await self.delisting_protection.evaluate_buy(row.symbol, config)
        except (ccxt.BaseError, TimeoutError, OSError, RuntimeError, ValueError):
            return await self._reject_prepared(
                operation_id, config, "blocked_delisting_check_unavailable"
            )
        if not decision.allowed:
            return await self._reject_prepared(
                operation_id,
                config,
                decision.reason_code or "blocked_delisting_check_unavailable",
            )

        async with lifecycle_mutation_coordinator.mutation(row.symbol) as admitted:
            if not admitted:
                return AccumulationExecutionResult(
                    operation_id, "prepared", "WAIT_MAINTENANCE"
                )
            await self.adapter.account_scope(config)
            outcome = await self._claim(operation_id, config, inputs, precision)
            if outcome == "claimed":

                async def submit_buy() -> dict[str, Any]:
                    async with asyncio.timeout(10):
                        return await self.adapter.exchange.submit_preflighted_spot_buy(
                            symbol=row.symbol,
                            amount=precision.amount,
                            price=precision.limit_price,
                            client_order_id=row.client_order_id,
                            config=config,
                        )

                try:
                    evidence = await PlacementWorkflow(self.intents).submit(
                        operation_id,
                        symbol=row.symbol,
                        side="buy",
                        submit=submit_buy,
                        require_acknowledgement=True,
                    )
                except ExchangeSubmissionIndeterminate:
                    return AccumulationExecutionResult(
                        operation_id, "indeterminate", "WAIT_RECONCILIATION"
                    )
        if outcome != "claimed":
            if outcome.startswith(("WAIT_", "blocked_")):
                return await self._reject_prepared(operation_id, config, outcome)
            return AccumulationExecutionResult(operation_id, outcome, "ALREADY_CLAIMED")
        try:
            result = await persist_accumulation_order(
                operation_id,
                evidence,
                account_scope=inputs.funding.account_scope,
                exchange_name=inputs.funding.exchange_name,
            )
        except AccumulationStateError:
            logging.warning(
                "Accumulation buy %s has incomplete evidence; lookup is required.",
                operation_id,
            )
            return AccumulationExecutionResult(
                operation_id, "accepted", "WAIT_RECONCILIATION"
            )
        if result.settled:
            await self.intents.transition(operation_id, PlacementIntentState.COMPLETED)
            return AccumulationExecutionResult(operation_id, "completed", "SETTLED")
        return AccumulationExecutionResult(
            operation_id, "accepted", "WAIT_RECONCILIATION"
        )
