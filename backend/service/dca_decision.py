"""Pure, immutable DCA evaluation contracts and trigger decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from service.dca_recovery_sizing import (
    RecoverySizingPolicy,
    calculate_recovery_execution_ceiling,
    calculate_recovery_execution_drift_percent,
    calculate_recovery_spacing_percent,
    calculate_recovery_target_percent,
    calculate_recovery_trigger_price,
)
from service.dca_safety_orders import (
    calculate_static_deviations,
    evaluate_static_dca_trigger,
)
from service.lifecycle_snapshot import LifecycleSnapshotIdentity


class DcaAction(StrEnum):
    """Side-effect-free action selected by DCA policy."""

    WAIT = "wait"
    PLACE_SAFETY_ORDER = "place_safety_order"
    SELL = "sell"
    ARM_TP_LIMIT = "arm_tp_limit"
    PLACE_REENTRY_BUY = "place_reentry_buy"


@dataclass(frozen=True)
class DcaEvaluationContext:
    """Immutable inputs captured before DCA policy evaluation.

    context -> pure decision -> locked snapshot revalidation -> execution
    """

    snapshot: LifecycleSnapshotIdentity
    current_price: float
    decision_timestamp_ms: int
    persisted_policy: RecoverySizingPolicy
    available_quote: float | None = None
    minimum_order_quote: float | None = None
    amount_precision: int | None = None
    strategy_name: str | None = None
    strategy_timeframe: str | None = None
    strategy_input_identity: str | None = None
    replay_identity: str | None = None


@dataclass(frozen=True)
class DcaDecision:
    """Pure DCA outcome carrying the identity used to calculate it."""

    action: DcaAction
    reason_code: str
    snapshot: LifecycleSnapshotIdentity
    requested_quote: float | None = None
    requested_amount: float | None = None
    maximum_execution_price: float | None = None
    max_deviation: float | None = None
    actual_deviation: float | None = None
    trigger_threshold: float | None = None
    next_so_percentage: float | None = None
    spacing_percent: float | None = None
    trigger_price: float | None = None
    atr_percent: float | None = None
    target_recovery_percent: float | None = None
    execution_drift_percent: float | None = None
    sell_reason: str | None = None

    @property
    def should_place(self) -> bool:
        """Return whether policy selected a safety-order placement."""
        return self.action is DcaAction.PLACE_SAFETY_ORDER

    def diagnostics(self) -> dict[str, float | str | bool]:
        """Return stable, JSON-compatible decision diagnostics."""
        values: dict[str, float | str | bool | None] = {
            "action": self.action.value,
            "reason": self.reason_code,
            "requested_quote": self.requested_quote,
            "requested_amount": self.requested_amount,
            "maximum_execution_price": self.maximum_execution_price,
            "max_deviation": self.max_deviation,
            "actual_deviation": self.actual_deviation,
            "trigger_threshold": self.trigger_threshold,
            "next_so_percentage": self.next_so_percentage,
            "spacing_percent": self.spacing_percent,
            "trigger_price": self.trigger_price,
            "atr_percent": self.atr_percent,
            "target_recovery_percent": self.target_recovery_percent,
            "execution_drift_percent": self.execution_drift_percent,
            "sell_reason": self.sell_reason,
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True)
class ExitActionContext:
    """Resolved, immutable inputs for TP/SL/sell action selection."""

    sell_signal: bool
    sell_reason: str | None
    is_unsellable: bool
    has_tp_limit_order: bool
    tp_limit_prearm_supported: bool
    tp_limit_prearm_ready: bool


@dataclass(frozen=True)
class SidestepExitContext:
    """Resolved, immutable inputs for a sidestep exit decision."""

    enabled: bool
    is_sidestep_mode: bool
    is_flat_waiting: bool
    is_unsellable: bool
    has_campaign: bool
    total_amount: float
    current_price: float
    take_profit_price: float
    strategy_signal: bool | None


@dataclass(frozen=True)
class WaitingReentryContext:
    """Resolved, immutable inputs for a sidestep re-entry decision."""

    is_sidestep_mode: bool
    is_flat_waiting: bool
    has_campaign_id: bool
    campaign_found: bool | None
    cooldown_active: bool
    strategy_signal: bool | None
    order_size: float
    current_price: float = 0.0
    waiting_reference_price: float = 0.0
    max_reentry_premium_pct: float = 0.0
    requires_fresh_long_signal: bool = False
    has_fresh_long_signal: bool = False


def calculate_sidestep_reentry_maximum_price(
    waiting_reference_price: float,
    max_reentry_premium_pct: float,
) -> float | None:
    """Return the inclusive re-entry price ceiling, or ``None`` when disabled."""
    if max_reentry_premium_pct <= 0:
        return None
    if waiting_reference_price <= 0:
        return None
    return waiting_reference_price * (1 + (max_reentry_premium_pct / 100))


def calculate_sidestep_exit_fallback_minimum_price(
    strategy_trigger_price: float,
    max_market_fallback_slippage_pct: float,
) -> float | None:
    """Return the sidestep market-fallback floor, or ``None`` when disabled."""
    if max_market_fallback_slippage_pct <= 0:
        return None
    if strategy_trigger_price <= 0:
        return None
    return strategy_trigger_price * (1 - (max_market_fallback_slippage_pct / 100))


def build_dca_evaluation_context(
    *,
    trade: dict[str, Any],
    config: dict[str, Any],
    current_price: float,
    decision_timestamp_ms: int,
    persisted_policy: RecoverySizingPolicy,
    available_quote: float | None = None,
    minimum_order_quote: float | None = None,
    amount_precision: int | None = None,
    strategy_name: str | None = None,
    strategy_timeframe: str | None = None,
    strategy_input_identity: str | None = None,
    replay_identity: str | None = None,
) -> DcaEvaluationContext:
    """Build one immutable context without leaking ORM or exchange objects."""
    existing_snapshot = trade.get("_lifecycle_snapshot")
    snapshot = (
        existing_snapshot
        if isinstance(existing_snapshot, LifecycleSnapshotIdentity)
        else LifecycleSnapshotIdentity.from_trade(trade, config)
    )
    return DcaEvaluationContext(
        snapshot=snapshot,
        current_price=float(current_price),
        decision_timestamp_ms=int(decision_timestamp_ms),
        persisted_policy=persisted_policy,
        available_quote=available_quote,
        minimum_order_quote=minimum_order_quote,
        amount_precision=amount_precision,
        strategy_name=strategy_name,
        strategy_timeframe=strategy_timeframe,
        strategy_input_identity=strategy_input_identity,
        replay_identity=replay_identity,
    )


def evaluate_static_dca_decision(
    context: DcaEvaluationContext,
    *,
    total_pnl: float,
    step_scale: float,
    price_deviation: float,
    safety_orders_count: int,
) -> DcaDecision:
    """Evaluate the legacy static ladder without I/O or mutable services."""
    max_deviation, actual_deviation = calculate_static_deviations(
        step_scale,
        price_deviation,
        safety_orders_count,
    )
    should_place, trigger_threshold, next_so_percentage = evaluate_static_dca_trigger(
        total_pnl,
        max_deviation,
        actual_deviation,
    )
    return DcaDecision(
        action=(DcaAction.PLACE_SAFETY_ORDER if should_place else DcaAction.WAIT),
        reason_code=(
            "static_trigger_reached" if should_place else "waiting_for_static_deviation"
        ),
        snapshot=context.snapshot,
        max_deviation=max_deviation,
        actual_deviation=actual_deviation,
        trigger_threshold=trigger_threshold,
        next_so_percentage=next_so_percentage,
    )


def evaluate_recovery_trigger_decision(
    context: DcaEvaluationContext,
    *,
    reference_price: float,
    reference_atr_percent: float,
    execution_atr_percent: float,
    strategy_signal: bool,
    strategy_payload_changed: bool,
) -> DcaDecision:
    """Evaluate recovery spacing and strategy gates without performing I/O."""
    policy = context.persisted_policy
    spacing_percent = calculate_recovery_spacing_percent(
        reference_atr_percent,
        context.snapshot.execution_count - 1,
        policy,
    )
    trigger_price = calculate_recovery_trigger_price(
        reference_price,
        spacing_percent,
    )
    target_recovery_percent = calculate_recovery_target_percent(
        execution_atr_percent,
        policy,
    )
    execution_drift_percent = calculate_recovery_execution_drift_percent(
        execution_atr_percent,
        policy,
    )
    maximum_execution_price = calculate_recovery_execution_ceiling(
        trigger_price,
        execution_atr_percent,
        policy,
    )

    action = DcaAction.WAIT
    if policy.maximum_deal_quote <= 0:
        reason_code = "missing_deal_budget"
    elif trigger_price <= 0 or context.current_price > trigger_price:
        reason_code = "waiting_for_atr_spacing"
    elif not strategy_signal:
        reason_code = "recovery_signal_not_matched"
    elif not strategy_payload_changed:
        reason_code = "recovery_signal_unchanged"
    else:
        action = DcaAction.PLACE_SAFETY_ORDER
        reason_code = "recovery_trigger_matched"

    return DcaDecision(
        action=action,
        reason_code=reason_code,
        snapshot=context.snapshot,
        maximum_execution_price=maximum_execution_price,
        spacing_percent=spacing_percent,
        trigger_price=trigger_price,
        atr_percent=execution_atr_percent,
        target_recovery_percent=target_recovery_percent,
        execution_drift_percent=execution_drift_percent,
    )


def evaluate_exit_action_decision(
    context: ExitActionContext,
) -> tuple[DcaAction, str, str | None]:
    """Select the final TP/SL action without performing lifecycle I/O."""
    if context.is_unsellable:
        return DcaAction.WAIT, "unsellable_remainder", None
    if context.sell_signal:
        if (
            context.has_tp_limit_order
            and context.sell_reason == "take_profit"
            and context.tp_limit_prearm_supported
        ):
            return DcaAction.WAIT, "waiting_for_tp_limit_fill", "take_profit"
        return (
            DcaAction.SELL,
            context.sell_reason or "sell_signal",
            context.sell_reason,
        )
    if (
        context.tp_limit_prearm_supported
        and not context.has_tp_limit_order
        and context.tp_limit_prearm_ready
    ):
        return DcaAction.ARM_TP_LIMIT, "tp_limit_prearm_ready", None
    return DcaAction.WAIT, "no_exit_trigger", None


def evaluate_sidestep_exit_decision(
    context: SidestepExitContext,
) -> tuple[DcaAction, str]:
    """Select a sidestep exit action without service or persistence access."""
    if not context.enabled:
        return DcaAction.WAIT, "sidestep_disabled"
    if not context.is_sidestep_mode:
        return DcaAction.WAIT, "not_sidestep_mode"
    if context.is_flat_waiting:
        return DcaAction.WAIT, "already_flat_waiting"
    if context.is_unsellable:
        return DcaAction.WAIT, "sidestep_unsellable"
    if not context.has_campaign:
        return DcaAction.WAIT, "active_missing_campaign"
    if context.total_amount <= 0:
        return DcaAction.WAIT, "active_missing_amount"
    if context.current_price >= context.take_profit_price:
        return DcaAction.WAIT, "exit_tp_gate"
    if context.strategy_signal is None:
        return DcaAction.WAIT, "sidestep_exit_strategy_required"
    if not context.strategy_signal:
        return DcaAction.WAIT, "sidestep_exit_strategy_not_matched"
    return DcaAction.SELL, "sidestep_exit"


def evaluate_waiting_reentry_decision(
    context: WaitingReentryContext,
) -> tuple[DcaAction, str]:
    """Select a waiting-campaign re-entry action without lifecycle I/O."""
    if not context.is_sidestep_mode:
        return DcaAction.WAIT, "not_sidestep_mode"
    if not context.is_flat_waiting:
        return DcaAction.WAIT, "not_flat_waiting"
    if not context.has_campaign_id:
        return DcaAction.WAIT, "waiting_missing_campaign"
    if context.campaign_found is None:
        return DcaAction.WAIT, "waiting_campaign_lookup_required"
    if not context.campaign_found:
        return DcaAction.WAIT, "waiting_campaign_not_found"
    if context.cooldown_active:
        return DcaAction.WAIT, "waiting_cooldown_active"
    if context.requires_fresh_long_signal and not context.has_fresh_long_signal:
        return DcaAction.WAIT, "waiting_fresh_long_signal_required"
    if context.strategy_signal is None:
        return DcaAction.WAIT, "sidestep_reentry_strategy_required"
    if not context.strategy_signal:
        return DcaAction.WAIT, "sidestep_reentry_strategy_not_matched"
    maximum_price = calculate_sidestep_reentry_maximum_price(
        context.waiting_reference_price,
        context.max_reentry_premium_pct,
    )
    if context.max_reentry_premium_pct > 0 and maximum_price is None:
        return DcaAction.WAIT, "waiting_reentry_reference_price_required"
    if maximum_price is not None and context.current_price > maximum_price:
        return DcaAction.WAIT, "waiting_reentry_price_above_limit"
    if context.order_size <= 0:
        return DcaAction.WAIT, "waiting_missing_reserved_quote"
    return DcaAction.PLACE_REENTRY_BUY, "sidestep_reentry"
