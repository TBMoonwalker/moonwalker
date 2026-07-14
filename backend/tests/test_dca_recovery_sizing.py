"""Regression tests for recovery-target DCA math."""

import pytest
from service.dca_recovery_sizing import (
    RECOVERY_TARGET_MODE,
    RecoverySizingPolicy,
    build_recovery_sizing_policy,
    calculate_recovery_sizing,
    calculate_recovery_spacing_percent,
    calculate_recovery_trigger_price,
)


def _policy(**overrides: float | str) -> RecoverySizingPolicy:
    values = {
        "mode": RECOVERY_TARGET_MODE,
        "atr_timeframe": "4h",
        "atr_length": 14,
        "spacing_atr_multiplier": 3.0,
        "minimum_spacing_percent": 5.0,
        "spacing_step_scale": 1.6,
        "recovery_atr_multiplier": 5.5,
        "minimum_recovery_percent": 12.0,
        "maximum_recovery_percent": 30.0,
        "maximum_deal_quote": 250.0,
        "minimum_tp_improvement_percent": 5.0,
    }
    values.update(overrides)
    return RecoverySizingPolicy.from_dict(values)


def test_0g_first_candidate_is_rejected_by_atr_spacing() -> None:
    policy = _policy()
    spacing = calculate_recovery_spacing_percent(1.789269, 0, policy)
    trigger = calculate_recovery_trigger_price(0.568, spacing)

    assert spacing == pytest.approx(5.367807)
    assert trigger == pytest.approx(0.53751086)
    assert 0.556 > trigger


def test_0g_recovery_target_counterfactual_preserves_deep_capital() -> None:
    policy = _policy()
    base_cost = 11.99048
    base_amount = 21.0899455

    first = calculate_recovery_sizing(
        total_cost=base_cost,
        total_amount=base_amount,
        fill_price=0.495,
        take_profit_percent=1.0,
        fee_ratio=0.0,
        atr_percent=1.5880084343,
        policy=policy,
    )
    assert first.should_place is True
    assert first.final_quote == pytest.approx(3.80108195)
    assert first.projected_tp_price == pytest.approx(0.5544)

    second = calculate_recovery_sizing(
        total_cost=base_cost + first.final_quote,
        total_amount=base_amount + (first.final_quote / 0.495),
        fill_price=0.306,
        take_profit_percent=1.0,
        fee_ratio=0.0,
        atr_percent=3.1376532711,
        policy=policy,
    )
    assert second.should_place is True
    assert second.final_quote == pytest.approx(34.61260727)
    assert second.projected_tp_price == pytest.approx(0.35880670)

    third = calculate_recovery_sizing(
        total_cost=base_cost + first.final_quote + second.final_quote,
        total_amount=(
            base_amount + (first.final_quote / 0.495) + (second.final_quote / 0.306)
        ),
        fill_price=0.175,
        take_profit_percent=1.0,
        fee_ratio=0.0,
        atr_percent=2.7412909853,
        policy=policy,
    )
    assert third.should_place is True
    assert third.final_quote == pytest.approx(158.66418016)
    assert third.projected_tp_price == pytest.approx(0.20138493)
    assert base_cost + first.final_quote + second.final_quote + third.final_quote == (
        pytest.approx(209.06834938)
    )


def test_sizing_skips_when_tp_is_already_inside_recovery_target() -> None:
    result = calculate_recovery_sizing(
        total_cost=11.99048,
        total_amount=21.0899455,
        fill_price=0.556,
        take_profit_percent=1.0,
        fee_ratio=0.0,
        atr_percent=1.8022608275,
        policy=_policy(),
    )

    assert result.should_place is False
    assert result.final_quote == 0.0
    assert result.reason == "tp_already_reachable"
    assert result.current_recovery_percent == pytest.approx(3.27797018)


def test_sizing_rejects_budget_cap_with_too_little_tp_improvement() -> None:
    result = calculate_recovery_sizing(
        total_cost=249.0,
        total_amount=500.0,
        fill_price=0.2,
        take_profit_percent=1.0,
        fee_ratio=0.0,
        atr_percent=3.0,
        policy=_policy(minimum_tp_improvement_percent=10.0),
    )

    assert result.capped is True
    assert result.final_quote == pytest.approx(1.0)
    assert result.should_place is False
    assert result.reason == "insufficient_tp_improvement"


def test_live_recovery_target_fails_closed_without_deal_budget() -> None:
    result = calculate_recovery_sizing(
        total_cost=12.0,
        total_amount=24.0,
        fill_price=0.3,
        take_profit_percent=1.0,
        fee_ratio=0.0,
        atr_percent=3.0,
        policy=_policy(maximum_deal_quote=0.0),
    )

    assert result.should_place is False
    assert result.final_quote == 0.0
    assert result.reason == "missing_deal_budget"


def test_policy_round_trip_normalizes_invalid_values() -> None:
    policy = RecoverySizingPolicy.from_dict(
        {
            "mode": "recovery_target",
            "atr_length": 1,
            "spacing_step_scale": 0,
            "minimum_recovery_percent": 20,
            "maximum_recovery_percent": 10,
        }
    )

    assert policy.mode == RECOVERY_TARGET_MODE
    assert policy.atr_length == 2
    assert policy.spacing_step_scale == 1.0
    assert policy.maximum_recovery_percent == 20.0


def test_policy_inherits_trading_timeframe_and_recovery_step_default() -> None:
    inherited = build_recovery_sizing_policy(
        {
            "timeframe": "30m",
            "dynamic_so_atr_timeframe": "trading",
        }
    )
    backtest_override = build_recovery_sizing_policy(
        {"dynamic_so_atr_timeframe": "trading"},
        trading_timeframe="4h",
    )
    explicit = build_recovery_sizing_policy(
        {
            "timeframe": "30m",
            "dynamic_so_atr_timeframe": "1d",
        }
    )

    assert inherited.atr_timeframe == "30m"
    assert inherited.spacing_step_scale == 1.6
    assert backtest_override.atr_timeframe == "4h"
    assert explicit.atr_timeframe == "1d"
