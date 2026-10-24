"""Five-second market-priority rounds and atomic accumulation buy preparation.

This internal coordinator prepares durable intents only. Exchange submission and
production account/market adapters are deliberately not wired here. Providers
run outside symbol/capital locks and transactions; admission uses their evidence
only after rechecking persisted identity and shared capital usage.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

import model
from service.accumulation_budget import (
    AccumulationFundingSnapshot,
    required_accumulation_quote,
    usable_accumulation_quote,
)
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_evaluation import AccumulationDecision, _guard, _proposal
from service.accumulation_initial import is_initial_asap_entry
from service.accumulation_lifecycle import _has_unsettled_execution
from service.accumulation_state import _load_context
from service.accumulation_strategy import (
    CAPABILITY,
    PRIORITY_PROTOCOL,
    SIZING_POLICY,
    AccumulationCandle,
    AccumulationObservations,
    AccumulationParameters,
    canonical_accumulation_priority,
    effective_accumulation_parameters,
)
from service.capital_budget import CapitalBudgetService
from service.database import run_sqlite_write_with_retry
from service.exchange_capabilities import build_client_order_id
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.placement_intents import (
    serialize_placement_payload,
)
from service.strategy_runtime import load_accumulation_strategy_version
from service.trading_controls import is_global_trading_paused
from tortoise.transactions import in_transaction

COLLECTION_MS = 5000


@dataclass(frozen=True)
class AccumulationOffer:
    """An evaluator proposal plus bounded canonical market evidence."""

    decision: AccumulationDecision
    priority_candles: tuple[AccumulationCandle, ...]


@dataclass(frozen=True)
class AccumulationAdmissionInputs:
    """Trusted fresh preflight evidence fetched without holding mutation locks."""

    funding: AccumulationFundingSnapshot
    ask_price: str
    quote_timestamp_ms: int
    minimum_quote: str


@dataclass(frozen=True)
class AccumulationAdmission:
    """Prepared journal identity or an actionable WAIT; never an exchange fill."""

    opportunity_id: str
    reason: str
    operation_id: str | None = None
    requested_quote: str | None = None
    reserved_quote: str | None = None


async def prepare_accumulation_buy(
    offer: AccumulationOffer,
    inputs: AccumulationAdmissionInputs,
    config: dict[str, Any],
    *,
    cutoff_ms: int,
    clock_ms: Callable[[], int],
) -> AccumulationAdmission:
    """Reevaluate spend and atomically bind journal, attempt and unresolved slot."""
    decision = offer.decision
    opportunity_id = decision.opportunity_id or ""

    def wait(reason: str) -> AccumulationAdmission:
        return AccumulationAdmission(opportunity_id, reason)

    if is_global_trading_paused(config):
        return wait("WAIT_GLOBAL_PAUSE")
    if config.get("trade_mode") != "accumulation":
        return wait("WAIT_STATE")
    initial = decision.reason == "BUY_INITIAL_ASAP"
    priority_close = effective_accumulation_parameters(
        AccumulationParameters(), config.get("timeframe")
    ).latest_close(cutoff_ms)
    priority = "0"
    if not initial:
        if (
            decision.capability != CAPABILITY
            or decision.priority_protocol != PRIORITY_PROTOCOL
            or decision.priority_close_ms != priority_close
        ):
            return wait("WAIT_DATA")
        priority = canonical_accumulation_priority(
            offer.priority_candles,
            close_ms=priority_close,
            timeframe=config.get("timeframe"),
        )
        if decision.priority_score is None or Decimal(
            canonical_decimal(decision.priority_score)
        ) != Decimal(priority):
            return wait("WAIT_DATA")
    activation = await model.AccumulationActivation.get(
        id=decision.identity.activation_id
    )
    funding = inputs.funding
    if (
        funding.account_scope != decision.identity.account_scope
        or funding.exchange_name != str(config.get("exchange") or "").strip().lower()
        or funding.quote_currency != activation.symbol.split("/")[-1]
    ):
        return wait("WAIT_ACCOUNT")
    version = await load_accumulation_strategy_version(
        decision.identity.strategy_version_id, timeframe=config.get("timeframe")
    )

    async def persist() -> AccumulationAdmission:
        async with in_transaction() as conn:
            opportunity_id = decision.opportunity_id or ""
            # Lock contention and DB retries must not freeze quote freshness.
            now_ms = clock_ms()
            if (
                not initial
                and effective_accumulation_parameters(
                    AccumulationParameters(), config.get("timeframe")
                ).latest_close(now_ms)
                != priority_close
            ):
                return wait("WAIT_DATA")
            current = await _load_context(
                decision.identity.activation_id, funding.account_scope, conn
            )
            if current.identity != decision.identity:
                return wait("WAIT_STATE")
            await activation.refresh_from_db(using_db=conn)
            if activation.state != "enabled" or activation.explicitly_paused:
                return wait("WAIT_LIFECYCLE")
            guard = _guard(
                activation.execution_guard_json, activation.consumption_revision
            )
            if not initial and current.observations is None:
                return wait("WAIT_REBASE")
            state = (
                AccumulationObservations.from_dict(current.observations)
                if current.observations is not None
                else None
            )
            if state is not None and (
                state.last_close_ms != current.last_processed_close_ms
                or state.timeframe not in {None, version.parameters.timeframe}
            ):
                return wait("WAIT_REBASE")
            if await _has_unsettled_execution(activation, conn):
                return wait("WAIT_ORDER")
            usable = await usable_accumulation_quote(config, funding, now_ms=now_ms)
            if initial:
                if config.get("signal") != "asap" or not await is_initial_asap_entry(
                    activation, conn
                ):
                    return wait("WAIT_STATE")
                if not 0 <= now_ms - inputs.quote_timestamp_ms <= 10000:
                    return wait("WAIT_DATA")
                requested = canonical_decimal(str(config.get("bo") or 0), positive=True)
                if usable is None or Decimal(usable) < Decimal(requested):
                    return wait("WAIT_BUDGET")
                if Decimal(requested) < Decimal(inputs.minimum_quote):
                    return wait("WAIT_MINIMUM")
                # No strategy candle or ranking window is involved in an ASAP entry.
                # A separate event kind keeps it out of ATR consumption/rearm guards.
                opportunity = await model.AccumulationOpportunity.create(
                    using_db=conn,
                    activation=activation,
                    generation=activation.generation,
                    strategy_version_id=version.id,
                    observation_epoch=activation.observation_epoch,
                    is_initial_entry=True,
                    signal_close_ms=now_ms,
                    expires_at_ms=now_ms + 10000,
                    signal_price=inputs.ask_price,
                    signal_atr="0",
                    signal_peak=None,
                )
                opportunity_id = str(opportunity.id)
                proposal = AccumulationDecision(
                    current.identity,
                    "BUY",
                    "BUY_INITIAL_ASAP",
                    opportunity_id=opportunity_id,
                    requested_quote=requested,
                )
            else:
                opportunity = await model.AccumulationOpportunity.get_or_none(
                    id=opportunity_id
                ).using_db(conn)
                if (
                    opportunity is None
                    or opportunity.activation_id != activation.id
                    or opportunity.generation != activation.generation
                    or opportunity.strategy_version_id != version.id
                    or opportunity.observation_epoch != activation.observation_epoch
                    or opportunity.signal_close_ms
                    != (state.last_close_ms if state else None)
                    or opportunity.signal_close_ms
                    != version.parameters.latest_close(now_ms)
                    or opportunity.signal_peak is None
                ):
                    return wait("WAIT_STATE")
                usable = await usable_accumulation_quote(config, funding, now_ms=now_ms)
                proposal = _proposal(
                    current.identity,
                    opportunity,
                    version.parameters,
                    now_ms=now_ms,
                    usable_quote=usable,
                    ask_price=inputs.ask_price,
                    quote_timestamp_ms=inputs.quote_timestamp_ms,
                    minimum_quote=inputs.minimum_quote,
                    priority=priority,
                    priority_close_ms=priority_close,
                    guard=guard,
                    previous_close=state.previous_close if state else None,
                )
                if proposal.action != "BUY" or proposal.requested_quote is None:
                    return wait(proposal.reason)
            required = required_accumulation_quote(proposal.requested_quote, config)
            mirror = float(required)
            if not math.isfinite(mirror):
                return wait("WAIT_BUDGET")
            if Decimal(str(mirror)) < required:
                mirror = math.nextafter(mirror, math.inf)
            order = {
                "symbol": activation.symbol,
                "_execution_scope": funding.account_scope,
                "side": "buy",
                "ordertype": "limit",
                "ordersize": proposal.requested_quote,
                "maximum_buy_price": opportunity.signal_price,
                "limit_price": opportunity.signal_price,
                "strategy_slug": version.slug,
                "strategy_version": version.version,
                "metadata_json": json.dumps(
                    {
                        "accumulation": {
                            "opportunity_id": opportunity_id,
                            "initial_entry": initial,
                            "timeframe": version.parameters.timeframe,
                            "sizing_policy": SIZING_POLICY,
                            "account_scope": funding.account_scope,
                            "strategy_version_id": version.id,
                            "generation": str(activation.generation),
                            "observation_epoch": activation.observation_epoch,
                            "admitted_revision": activation.revision + 1,
                            "consumption_revision": activation.consumption_revision,
                            "priority_protocol": PRIORITY_PROTOCOL,
                            "priority_close_ms": priority_close,
                            "priority_score": priority,
                            "round_cutoff_ms": cutoff_ms,
                            "requested_quote": proposal.requested_quote,
                            "reserved_quote": str(required),
                        }
                    },
                    sort_keys=True,
                ),
            }
            if not str(config.get("exchange") or "").strip():
                return wait("WAIT_EXECUTION_DISABLED")
            operation_id = f"buy-{uuid4().hex}"
            # The symbol lock and unresolved-slot constraint own deduplication.
            # Do not take the generic journal lock inside a DB transaction: other
            # writers take that lock before waiting for the SQLite connection.
            placement = await model.PlacementIntent.create(
                using_db=conn,
                operation_id=operation_id,
                client_order_id=build_client_order_id(operation_id),
                exchange_name=funding.exchange_name,
                symbol=activation.symbol,
                action="buy",
                side="buy",
                order_type="limit",
                state="prepared",
                requested_quote=float(proposal.requested_quote),
                maximum_price=float(opportunity.signal_price),
                reserved_quote=mirror,
                request_json=serialize_placement_payload(order),
            )
            await model.AccumulationAttempt.create(
                using_db=conn,
                opportunity=opportunity,
                placement=placement,
            )
            opportunity.unresolved_slot = activation.id
            opportunity.status = "unresolved"
            await opportunity.save(using_db=conn)
            activation.revision += 1
            await activation.save(using_db=conn)
            return AccumulationAdmission(
                opportunity_id,
                "PREPARED",
                operation_id,
                proposal.requested_quote,
                str(required),
            )

    async with lifecycle_mutation_coordinator.mutation(activation.symbol) as admitted:
        if not admitted:
            return wait("WAIT_MAINTENANCE")
        # Same lock as ordinary DCA leases. There is no exchange I/O in persist.
        async with CapitalBudgetService._lock:
            return await run_sqlite_write_with_retry(
                persist, "reserving accumulation buy"
            )


class AccumulationPortfolioCoordinator:
    """Collect change-driven offers; callers schedule at next_cutoff_ms.

    A WAIT does not automatically requeue or start another round. Runtime changes
    must supply a fresh evaluator proposal. In-memory offers may be lost on a
    restart; durable opportunities and prepared commitments are never lost.
    """

    def __init__(
        self,
        config: dict[str, Any],
        provider: Callable[[AccumulationOffer], Awaitable[AccumulationAdmissionInputs]],
        *,
        clock_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    ) -> None:
        self._config = dict(config)
        self._provider = provider
        self._clock_ms = clock_ms
        self._offers: list[tuple[int, AccumulationOffer]] = []
        self._running = False
        self.next_cutoff_ms: int | None = None

    def offer(
        self,
        decision: AccumulationDecision,
        priority_candles: Sequence[AccumulationCandle],
    ) -> None:
        """Queue a changed candidate without resetting an open collection window."""
        if not decision.opportunity_id:
            return
        now = self._clock_ms()
        # Keep one latest value per opportunity per window, including late arrivals.
        boundary = self.next_cutoff_ms
        late = boundary is not None and now > boundary
        self._offers = [
            (at, old)
            for at, old in self._offers
            if old.decision.opportunity_id != decision.opportunity_id
            or (boundary is not None and (at > boundary) != late)
        ]
        self._offers.append((now, AccumulationOffer(decision, tuple(priority_candles))))
        if boundary is None:
            self.next_cutoff_ms = now + COLLECTION_MS

    async def run_due(self) -> list[AccumulationAdmission]:
        """Drain a cutoff snapshot by verified severity, original time, then symbol."""
        cutoff = self.next_cutoff_ms
        if self._running or cutoff is None or self._clock_ms() < cutoff:
            return []
        self._running = True
        offers = [offer for at, offer in self._offers if at <= cutoff]
        self._offers = [(at, offer) for at, offer in self._offers if at > cutoff]
        self.next_cutoff_ms = min(
            (at + COLLECTION_MS for at, _ in self._offers), default=None
        )
        results = []
        try:
            ranked = []
            close = effective_accumulation_parameters(
                AccumulationParameters(), self._config.get("timeframe")
            ).latest_close(cutoff)
            for offer in offers:
                decision = offer.decision
                row = await model.AccumulationOpportunity.get_or_none(
                    id=decision.opportunity_id
                )
                if row is None or row.expires_at_ms <= cutoff or row.consumed_at:
                    continue
                try:
                    score = Decimal(
                        canonical_accumulation_priority(
                            offer.priority_candles,
                            close_ms=close,
                            timeframe=self._config.get("timeframe"),
                        )
                    )
                    if decision.priority_score is None or score != Decimal(
                        canonical_decimal(decision.priority_score)
                    ):
                        raise AccumulationStateError("Priority evidence changed.")
                except AccumulationStateError:
                    results.append(AccumulationAdmission(str(row.id), "WAIT_DATA"))
                    continue
                activation = await model.AccumulationActivation.get(
                    id=row.activation_id
                )
                ranked.append(
                    (-score, row.created_at, activation.symbol.upper(), offer)
                )
            ranked.sort(key=lambda row: row[:3])
            for _, _, _, offer in ranked:
                try:
                    async with asyncio.timeout(10):
                        inputs = await self._provider(offer)
                    result = await prepare_accumulation_buy(
                        offer,
                        inputs,
                        self._config,
                        cutoff_ms=cutoff,
                        clock_ms=self._clock_ms,
                    )
                except (AccumulationStateError, TimeoutError):
                    result = AccumulationAdmission(
                        offer.decision.opportunity_id or "", "WAIT_DATA"
                    )
                results.append(result)
            return results
        finally:
            self._running = False
