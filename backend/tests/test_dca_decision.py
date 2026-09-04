"""Pure branch coverage for immutable DCA decisions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from service.dca_decision import (
    DcaAction,
    DcaEvaluationContext,
    ExitActionContext,
    SidestepExitContext,
    WaitingReentryContext,
    build_dca_evaluation_context,
    calculate_sidestep_exit_fallback_minimum_price,
    evaluate_exit_action_decision,
    evaluate_recovery_trigger_decision,
    evaluate_sidestep_exit_decision,
    evaluate_static_dca_decision,
    evaluate_waiting_reentry_decision,
)
from service.dca_recovery_sizing import RecoverySizingPolicy


def _context(
    *,
    current_price: float = 90.0,
    policy: RecoverySizingPolicy | None = None,
) -> DcaEvaluationContext:
    return build_dca_evaluation_context(
        trade={
            "symbol": "ETH/USDC",
            "deal_id": "deal-1",
            "campaign_id": "campaign-1",
            "execution_count": 2,
            "safetyorders_count": 1,
            "dca_sizing_mode": "recovery_target",
        },
        config={"dry_run": True, "bo": 25.0},
        current_price=current_price,
        decision_timestamp_ms=1234,
        persisted_policy=policy or RecoverySizingPolicy(mode="recovery_target"),
        available_quote=100.0,
        minimum_order_quote=5.0,
        amount_precision=6,
        strategy_name="ema_cross",
        strategy_timeframe="1h",
        strategy_input_identity="candle-42",
        replay_identity="replay-1",
    )


def test_evaluation_context_and_decision_are_frozen() -> None:
    context = _context()
    decision = evaluate_static_dca_decision(
        context,
        total_pnl=-5.0,
        step_scale=1.5,
        price_deviation=2.0,
        safety_orders_count=1,
    )

    with pytest.raises(FrozenInstanceError):
        context.current_price = 1.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.reason_code = "changed"  # type: ignore[misc]

    assert decision.action is DcaAction.PLACE_SAFETY_ORDER
    assert decision.snapshot is context.snapshot


@pytest.mark.parametrize(
    (
        "current_price",
        "policy",
        "strategy_signal",
        "payload_changed",
        "expected_reason",
        "expected_action",
    ),
    [
        (
            90.0,
            replace(RecoverySizingPolicy(mode="recovery_target"), maximum_deal_quote=0),
            True,
            True,
            "missing_deal_budget",
            DcaAction.WAIT,
        ),
        (
            99.0,
            RecoverySizingPolicy(mode="recovery_target"),
            True,
            True,
            "waiting_for_atr_spacing",
            DcaAction.WAIT,
        ),
        (
            90.0,
            RecoverySizingPolicy(mode="recovery_target"),
            False,
            True,
            "recovery_signal_not_matched",
            DcaAction.WAIT,
        ),
        (
            90.0,
            RecoverySizingPolicy(mode="recovery_target"),
            True,
            False,
            "recovery_signal_unchanged",
            DcaAction.WAIT,
        ),
        (
            90.0,
            RecoverySizingPolicy(mode="recovery_target"),
            True,
            True,
            "recovery_trigger_matched",
            DcaAction.PLACE_SAFETY_ORDER,
        ),
    ],
)
def test_recovery_decision_covers_every_reason_without_service_mocks(
    current_price: float,
    policy: RecoverySizingPolicy,
    strategy_signal: bool,
    payload_changed: bool,
    expected_reason: str,
    expected_action: DcaAction,
) -> None:
    decision = evaluate_recovery_trigger_decision(
        _context(current_price=current_price, policy=policy),
        reference_price=100.0,
        reference_atr_percent=2.0,
        execution_atr_percent=1.5,
        strategy_signal=strategy_signal,
        strategy_payload_changed=payload_changed,
    )

    assert decision.reason_code == expected_reason
    assert decision.action is expected_action
    assert decision.spacing_percent == pytest.approx(9.6)
    assert decision.trigger_price == pytest.approx(90.4)
    assert decision.maximum_execution_price is not None
    assert decision.diagnostics()["reason"] == expected_reason


@pytest.mark.parametrize(
    ("context", "expected_action", "expected_reason"),
    [
        (
            ExitActionContext(True, "stop_loss", False, False, False, False),
            DcaAction.SELL,
            "stop_loss",
        ),
        (
            ExitActionContext(True, "take_profit", False, True, True, False),
            DcaAction.WAIT,
            "waiting_for_tp_limit_fill",
        ),
        (
            ExitActionContext(False, None, False, False, True, True),
            DcaAction.ARM_TP_LIMIT,
            "tp_limit_prearm_ready",
        ),
        (
            ExitActionContext(False, None, True, False, False, False),
            DcaAction.WAIT,
            "unsellable_remainder",
        ),
        (
            ExitActionContext(False, None, False, False, False, False),
            DcaAction.WAIT,
            "no_exit_trigger",
        ),
    ],
)
def test_exit_action_decisions_are_pure(
    context: ExitActionContext,
    expected_action: DcaAction,
    expected_reason: str,
) -> None:
    action, reason, _sell_reason = evaluate_exit_action_decision(context)

    assert action is expected_action
    assert reason == expected_reason


@pytest.mark.parametrize(
    ("changes", "expected_action", "expected_reason"),
    [
        ({"enabled": False}, DcaAction.WAIT, "sidestep_disabled"),
        ({"is_sidestep_mode": False}, DcaAction.WAIT, "not_sidestep_mode"),
        ({"is_flat_waiting": True}, DcaAction.WAIT, "already_flat_waiting"),
        ({"is_unsellable": True}, DcaAction.WAIT, "sidestep_unsellable"),
        ({"has_campaign": False}, DcaAction.WAIT, "active_missing_campaign"),
        ({"total_amount": 0.0}, DcaAction.WAIT, "active_missing_amount"),
        ({"current_price": 110.0}, DcaAction.WAIT, "exit_tp_gate"),
        (
            {"strategy_signal": None},
            DcaAction.WAIT,
            "sidestep_exit_strategy_required",
        ),
        (
            {"strategy_signal": False},
            DcaAction.WAIT,
            "sidestep_exit_strategy_not_matched",
        ),
        ({"strategy_signal": True}, DcaAction.SELL, "sidestep_exit"),
    ],
)
def test_sidestep_exit_decisions_cover_every_reason_without_mocks(
    changes: dict[str, object],
    expected_action: DcaAction,
    expected_reason: str,
) -> None:
    values = {
        "enabled": True,
        "is_sidestep_mode": True,
        "is_flat_waiting": False,
        "is_unsellable": False,
        "has_campaign": True,
        "total_amount": 1.0,
        "current_price": 90.0,
        "take_profit_price": 105.0,
        "strategy_signal": True,
        **changes,
    }

    action, reason = evaluate_sidestep_exit_decision(SidestepExitContext(**values))

    assert action is expected_action
    assert reason == expected_reason


@pytest.mark.parametrize(
    ("changes", "expected_action", "expected_reason"),
    [
        ({"is_sidestep_mode": False}, DcaAction.WAIT, "not_sidestep_mode"),
        ({"is_flat_waiting": False}, DcaAction.WAIT, "not_flat_waiting"),
        ({"has_campaign_id": False}, DcaAction.WAIT, "waiting_missing_campaign"),
        (
            {"campaign_found": None},
            DcaAction.WAIT,
            "waiting_campaign_lookup_required",
        ),
        (
            {"campaign_found": False},
            DcaAction.WAIT,
            "waiting_campaign_not_found",
        ),
        ({"cooldown_active": True}, DcaAction.WAIT, "waiting_cooldown_active"),
        (
            {
                "requires_fresh_long_signal": True,
                "has_fresh_long_signal": False,
            },
            DcaAction.WAIT,
            "waiting_fresh_long_signal_required",
        ),
        (
            {"strategy_signal": None},
            DcaAction.WAIT,
            "sidestep_reentry_strategy_required",
        ),
        (
            {"strategy_signal": False},
            DcaAction.WAIT,
            "sidestep_reentry_strategy_not_matched",
        ),
        (
            {"order_size": 0.0},
            DcaAction.WAIT,
            "waiting_missing_reserved_quote",
        ),
        (
            {
                "current_price": 106.0,
                "waiting_reference_price": 100.0,
                "max_reentry_premium_pct": 5.0,
            },
            DcaAction.WAIT,
            "waiting_reentry_price_above_limit",
        ),
        (
            {"max_reentry_premium_pct": 5.0},
            DcaAction.WAIT,
            "waiting_reentry_reference_price_required",
        ),
        (
            {"strategy_signal": True},
            DcaAction.PLACE_REENTRY_BUY,
            "sidestep_reentry",
        ),
    ],
)
def test_waiting_reentry_decisions_cover_every_reason_without_mocks(
    changes: dict[str, object],
    expected_action: DcaAction,
    expected_reason: str,
) -> None:
    values = {
        "is_sidestep_mode": True,
        "is_flat_waiting": True,
        "has_campaign_id": True,
        "campaign_found": True,
        "cooldown_active": False,
        "strategy_signal": True,
        "order_size": 50.0,
        "has_fresh_long_signal": True,
        **changes,
    }

    action, reason = evaluate_waiting_reentry_decision(WaitingReentryContext(**values))

    assert action is expected_action
    assert reason == expected_reason


@pytest.mark.parametrize(
    ("trigger_price", "slippage_pct", "expected"),
    [
        (100.0, 1.0, 99.0),
        (100.0, 0.0, None),
        (0.0, 1.0, None),
    ],
)
def test_sidestep_exit_fallback_minimum_price(
    trigger_price: float,
    slippage_pct: float,
    expected: float | None,
) -> None:
    assert (
        calculate_sidestep_exit_fallback_minimum_price(trigger_price, slippage_pct)
        == expected
    )
