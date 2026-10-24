"""Revision-checked strategy evaluation and frozen accumulation candidates.

Callers provide bounded completed candles and fresh budget/quote snapshots.
BUY is a proposal, never permission to submit without fresh capital admission.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, localcontext
from typing import Any

import model
from service.accumulation_contracts import (
    AccumulationIdentity,
    AccumulationStateError,
    canonical_decimal,
    encode_observations,
)
from service.accumulation_lifecycle import _has_unsettled_execution
from service.accumulation_state import AccumulationConflictError, _load_context
from service.accumulation_strategy import (
    CAPABILITY,
    PRIORITY_PROTOCOL,
    AccumulationCandle,
    AccumulationGuard,
    AccumulationMarket,
    AccumulationObservations,
    AccumulationParameters,
    accumulation_requested_quote,
    accumulation_signal_reason,
    advance_accumulation_observations,
    calculate_accumulation_market,
    canonical_accumulation_priority,
)
from service.accumulation_wait import accumulation_wait_condition
from service.database import run_sqlite_write_with_retry
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.strategy_runtime import load_accumulation_strategy_version
from tortoise.transactions import in_transaction


@dataclass(frozen=True)
class AccumulationDecision:
    """Typed WAIT/BUY proposal with its persisted lifecycle and strategy identity."""

    identity: AccumulationIdentity
    action: str
    reason: str
    opportunity_id: str | None = None
    signal_close_ms: int | None = None
    expires_at_ms: int | None = None
    signal_price: str | None = None
    signal_atr: str | None = None
    severity: str | None = None
    fraction: str | None = None
    requested_quote: str | None = None
    priority_score: str | None = None
    priority_close_ms: int | None = None
    capability: str = CAPABILITY
    priority_protocol: str = PRIORITY_PROTOCOL
    wait_condition: dict[str, Any] | None = None


def _guard(raw: str | None, revision: int) -> AccumulationGuard | None:
    if raw is None:
        if revision != 0:
            raise AccumulationStateError("Execution guard is missing.")
        return None
    result = AccumulationGuard.from_dict(json.loads(raw))
    if result.consumption_revision != revision:
        raise AccumulationStateError("Execution guard consumption revision changed.")
    return result


async def _anchor_initial_fill(
    activation: model.AccumulationActivation,
    market: AccumulationMarket,
    conn: Any,
) -> AccumulationGuard | None:
    """Freeze spacing from settled BO execution and the first validated ATR.

    ASAP needs no market history to buy. Its immutable signal records the ask
    and zero ATR, so only its owned fill checkpoint can establish this anchor.
    Imported inventory without an ASAP opportunity retains first-dip behavior.
    """
    initial = (
        await model.AccumulationOpportunity.filter(
            activation=activation,
            generation=activation.generation,
            is_initial_entry=True,
            consumed_at__isnull=False,
        )
        .using_db(conn)
        .get_or_none()
    )
    if initial is None:
        return None
    holding = await model.OpenTrades.get_or_none(id=activation.holding_id).using_db(
        conn
    )
    checkpoints = await model.AccumulationFillCheckpoint.filter(
        activation=activation,
        placement__accumulation_attempt__opportunity_id=initial.id,
    ).using_db(conn)
    checkpoints = [
        checkpoint
        for checkpoint in checkpoints
        if Decimal(canonical_decimal(checkpoint.filled)) > 0
    ]
    if (
        holding is None
        or len(checkpoints) != 1
        or checkpoints[0].deal_id != holding.deal_id
        or not checkpoints[0].terminal
        or not checkpoints[0].fees_complete
    ):
        raise AccumulationStateError("Settled initial fill evidence is required.")
    checkpoint = checkpoints[0]
    filled = Decimal(canonical_decimal(checkpoint.filled, positive=True))
    cost = Decimal(canonical_decimal(checkpoint.quote_cost, positive=True))
    try:
        evidence = json.loads(checkpoint.evidence_json)
        timestamp = evidence["timestamp_ms"]
    except (ValueError, KeyError, TypeError) as exc:
        raise AccumulationStateError("Initial fill timestamp is missing.") from exc
    if type(timestamp) is not int or timestamp < 0:
        raise AccumulationStateError("Initial fill timestamp is invalid.")
    with localcontext() as context:
        context.prec = 50
        price = canonical_decimal(str(cost / filled), positive=True)
    guard = AccumulationGuard.from_dict(
        {
            "opportunity_id": str(initial.id),
            "signal_close_ms": timestamp,
            "signal_price": price,
            "signal_atr": canonical_decimal(market.atr, positive=True),
            "strategy_version_id": initial.strategy_version_id,
            "consumption_revision": 1,
        }
    )
    activation.consumption_revision = guard.consumption_revision
    activation.execution_guard_json = json.dumps(asdict(guard), sort_keys=True)
    initial.consumption_revision = guard.consumption_revision
    await initial.save(using_db=conn, update_fields=["consumption_revision"])
    return guard


def _proposal(
    identity: AccumulationIdentity,
    opportunity: model.AccumulationOpportunity,
    parameters: AccumulationParameters,
    *,
    now_ms: int,
    usable_quote: str | None,
    ask_price: str | None,
    quote_timestamp_ms: int | None,
    minimum_quote: str | None,
    priority: str | None,
    priority_close_ms: int,
) -> AccumulationDecision:
    with localcontext() as context:
        context.prec = 50
        severity = str(
            max(
                Decimal(0),
                (Decimal(opportunity.signal_peak) - Decimal(opportunity.signal_price))
                / Decimal(opportunity.signal_atr),
            )
        )
    result = AccumulationDecision(
        identity,
        "WAIT",
        "WAIT_DATA",
        str(opportunity.id),
        opportunity.signal_close_ms,
        opportunity.expires_at_ms,
        opportunity.signal_price,
        opportunity.signal_atr,
        severity,
        priority_score=priority,
        priority_close_ms=priority_close_ms,
    )
    if now_ms >= opportunity.expires_at_ms:
        return replace(result, reason="WAIT_EXPIRED")
    if opportunity.consumed_at is not None:
        return replace(result, reason="WAIT_CONSUMED")
    if opportunity.status not in {"candidate", "retryable"}:
        return replace(result, reason="WAIT_STATE")
    if opportunity.next_retry_at is not None and now_ms < int(
        opportunity.next_retry_at.timestamp() * 1000
    ):
        return replace(result, reason="WAIT_RETRY")
    if priority is None:
        return result
    if usable_quote is None:
        return replace(result, reason="WAIT_BUDGET")
    try:
        usable = canonical_decimal(usable_quote)
    except AccumulationStateError:
        return replace(result, reason="WAIT_BUDGET")
    fraction, requested = accumulation_requested_quote(severity, usable, parameters)
    result = replace(result, fraction=fraction, requested_quote=requested)
    if Decimal(requested) == 0:
        return replace(result, reason="WAIT_BUDGET")
    if (
        type(quote_timestamp_ms) is not int
        or not 0 <= now_ms - quote_timestamp_ms <= 10000
    ):
        return result
    try:
        ask = canonical_decimal(ask_price, positive=True)
        minimum = canonical_decimal(minimum_quote)
    except AccumulationStateError:
        return result
    if Decimal(ask) > Decimal(opportunity.signal_price):
        with localcontext() as context:
            context.prec = 50
            change = (Decimal(opportunity.signal_price) / Decimal(ask) - 1) * 100
        return replace(
            result,
            reason="WAIT_PRICE",
            wait_condition={
                "reason": "WAIT_PRICE",
                "timeframe": parameters.timeframe,
                "observed_close_ms": opportunity.signal_close_ms,
                "observed_price": ask,
                "price_basis": "ask",
                "next_close_ms": opportunity.expires_at_ms,
                "levels": [
                    {
                        "kind": "execution_price",
                        "direction": "at_or_below",
                        "target_price": opportunity.signal_price,
                        "change_percent": str(change),
                    }
                ],
            },
        )
    if Decimal(requested) < Decimal(minimum):
        return replace(result, reason="WAIT_MINIMUM")
    return replace(result, action="BUY", reason="BUY_OPPORTUNITY")


async def evaluate_accumulation(
    expected: AccumulationIdentity,
    candles: Sequence[AccumulationCandle],
    *,
    priority_candles: Sequence[AccumulationCandle],
    now_ms: int,
    usable_quote: str | None,
    ask_price: str | None,
    quote_timestamp_ms: int | None,
    minimum_quote: str | None,
) -> AccumulationDecision:
    """Advance one current candle and freeze its opportunity atomically.

    Warmup supplies observations at the baseline. A missed observation interval
    requires bounded rebase; it never backfills buys. Missing data does not
    advance the stored candle or manufacture a fresh state.
    """
    version = await load_accumulation_strategy_version(expected.strategy_version_id)
    if (
        version.slug != expected.strategy_slug
        or version.version != expected.strategy_version
    ):
        raise AccumulationStateError("Pinned strategy identity does not match.")
    parameters = version.parameters
    close_ms = parameters.latest_close(now_ms)
    try:
        market = await asyncio.to_thread(
            calculate_accumulation_market, candles, parameters, close_ms=close_ms
        )
    except AccumulationStateError:
        return AccumulationDecision(expected, "WAIT", "WAIT_DATA")
    priority_close = AccumulationParameters().latest_close(now_ms)
    try:
        priority = canonical_accumulation_priority(
            priority_candles, close_ms=priority_close
        )
    except AccumulationStateError:
        priority = None

    async def persist() -> AccumulationDecision:
        async with in_transaction() as conn:
            current = await _load_context(
                expected.activation_id, expected.account_scope, conn
            )
            if current.identity != expected:
                raise AccumulationConflictError(
                    "Accumulation decision identity changed; reload."
                )
            activation = await model.AccumulationActivation.get(
                id=expected.activation_id
            ).using_db(conn)
            if expected.state != "enabled" or expected.explicitly_paused:
                return AccumulationDecision(expected, "WAIT", "WAIT_LIFECYCLE")
            guard = _guard(
                activation.execution_guard_json, expected.consumption_revision
            )
            if current.observations is None:
                return AccumulationDecision(expected, "WAIT", "WAIT_REBASE")
            state = AccumulationObservations.from_dict(current.observations)
            if state.last_close_ms != current.last_processed_close_ms:
                raise AccumulationStateError(
                    "Observation candle identity is inconsistent."
                )
            if market.close_ms <= expected.baseline_close_ms:
                return AccumulationDecision(
                    expected,
                    "WAIT",
                    "WAIT_BASELINE",
                    wait_condition=accumulation_wait_condition(
                        market, state, guard, parameters, "WAIT_BASELINE"
                    ),
                )
            if (
                market.close_ms < state.last_close_ms
                or market.close_ms > state.last_close_ms + parameters.interval_ms
            ):
                return AccumulationDecision(expected, "WAIT", "WAIT_REBASE")
            unsettled = await _has_unsettled_execution(activation, conn)
            if guard is None and not unsettled:
                guard = await _anchor_initial_fill(activation, market, conn)
            updated_state = advance_accumulation_observations(
                state, market, guard, parameters
            )
            identity = replace(
                expected, consumption_revision=activation.consumption_revision
            )
            if updated_state != state:
                activation.revision += 1
                await activation.save(using_db=conn)
                await (
                    model.AccumulationStrategyState.filter(
                        activation=activation,
                        strategy_version_id=version.id,
                        observation_epoch=expected.observation_epoch,
                    )
                    .using_db(conn)
                    .update(
                        value_json=encode_observations(asdict(updated_state)),
                        last_processed_close_ms=market.close_ms,
                        revision=activation.revision,
                    )
                )
                identity = replace(identity, revision=activation.revision)
            if unsettled:
                return AccumulationDecision(identity, "WAIT", "WAIT_ORDER")
            opportunity = await model.AccumulationOpportunity.get_or_none(
                activation=activation,
                observation_epoch=expected.observation_epoch,
                signal_close_ms=market.close_ms,
            ).using_db(conn)
            initial_anchor = (
                guard is not None
                and await model.AccumulationOpportunity.filter(
                    id=guard.opportunity_id,
                    activation=activation,
                    generation=activation.generation,
                    is_initial_entry=True,
                )
                .using_db(conn)
                .exists()
            )
            # An old pending first-dip candidate must also respect the BO anchor.
            if opportunity is None or (
                initial_anchor and opportunity.consumed_at is None
            ):
                reason = accumulation_signal_reason(
                    market, updated_state, guard, parameters
                )
                if not reason.startswith("BUY_"):
                    return AccumulationDecision(
                        identity,
                        "WAIT",
                        reason,
                        wait_condition=accumulation_wait_condition(
                            market, updated_state, guard, parameters, reason
                        ),
                    )
            if opportunity is None:
                if market.close_ms == state.last_close_ms:
                    return AccumulationDecision(
                        identity,
                        "WAIT",
                        "WAIT_NEW_CANDLE",
                        wait_condition=accumulation_wait_condition(
                            market, updated_state, guard, parameters, "WAIT_NEW_CANDLE"
                        ),
                    )
                opportunity = await model.AccumulationOpportunity.create(
                    using_db=conn,
                    activation=activation,
                    generation=activation.generation,
                    strategy_version_id=version.id,
                    observation_epoch=expected.observation_epoch,
                    signal_close_ms=market.close_ms,
                    expires_at_ms=market.close_ms + parameters.interval_ms,
                    signal_price=market.close,
                    signal_atr=market.atr,
                    signal_peak=market.peak,
                )
            if (
                opportunity.generation != activation.generation
                or opportunity.strategy_version_id != version.id
            ):
                raise AccumulationStateError(
                    "Frozen opportunity identity is inconsistent."
                )
            if opportunity.signal_peak is None or (
                Decimal(opportunity.signal_price) != Decimal(market.close)
                or Decimal(opportunity.signal_atr) != Decimal(market.atr)
                or Decimal(opportunity.signal_peak) != Decimal(market.peak)
            ):
                return AccumulationDecision(identity, "WAIT", "WAIT_DATA")
            return _proposal(
                identity,
                opportunity,
                parameters,
                now_ms=now_ms,
                usable_quote=usable_quote,
                ask_price=ask_price,
                quote_timestamp_ms=quote_timestamp_ms,
                minimum_quote=minimum_quote,
                priority=priority,
                priority_close_ms=priority_close,
            )

    activation = await model.AccumulationActivation.get(id=expected.activation_id)
    async with lifecycle_mutation_coordinator.mutation(activation.symbol) as admitted:
        if not admitted:
            return AccumulationDecision(expected, "WAIT", "WAIT_MAINTENANCE")
        return await run_sqlite_write_with_retry(
            persist, "evaluating accumulation candle"
        )
