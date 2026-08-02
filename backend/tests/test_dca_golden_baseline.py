"""Golden regression coverage for pre-refactor DCA decisions and trade history."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from service.dca_decision import (
    build_dca_evaluation_context,
    evaluate_recovery_trigger_decision,
    evaluate_static_dca_decision,
)
from service.dca_recovery_sizing import (
    RecoverySizingPolicy,
    calculate_recovery_sizing,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dca_golden_v1.json"
FLOAT_TOLERANCE = 1e-8


def _load_golden_fixture() -> dict[str, Any]:
    """Load the versioned, sanitized baseline captured before the DCA refactor."""
    with FIXTURE_PATH.open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def _assert_expected_values(
    actual: dict[str, Any],
    expected: dict[str, Any],
    *,
    case_name: str,
) -> None:
    """Compare an evaluated case with strict semantics and float tolerance."""
    assert actual.keys() == expected.keys(), f"{case_name}: result shape changed"
    for key, expected_value in expected.items():
        actual_value = actual[key]
        if isinstance(expected_value, float):
            assert actual_value == pytest.approx(
                expected_value,
                abs=FLOAT_TOLERANCE,
                rel=1e-12,
            ), f"{case_name}: {key} changed"
        else:
            assert actual_value == expected_value, f"{case_name}: {key} changed"


def _evaluate_live_recovery_case(
    case: dict[str, Any],
    policy: RecoverySizingPolicy,
) -> dict[str, Any]:
    """Evaluate one sanitized live recovery decision through the pure boundary."""
    inputs = case["input"]
    current_price = float(
        inputs.get("current_price")
        or inputs.get("actual_fill_price")
        or inputs["reference_price"]
    )
    context = build_dca_evaluation_context(
        trade={
            "symbol": "GOLDEN/USDC",
            "deal_id": "golden-deal",
            "execution_count": inputs["filled_safety_orders"] + 1,
            "safetyorders_count": inputs["filled_safety_orders"],
        },
        config={"dry_run": True},
        current_price=current_price,
        decision_timestamp_ms=0,
        persisted_policy=policy,
        replay_identity=case["name"],
    )
    decision = evaluate_recovery_trigger_decision(
        context,
        reference_price=inputs["reference_price"],
        reference_atr_percent=inputs["reference_atr_percent"],
        execution_atr_percent=inputs["execution_atr_percent"],
        strategy_signal=True,
        strategy_payload_changed=True,
    )
    actual: dict[str, Any] = {
        "spacing_percent": decision.spacing_percent,
        "trigger_price": decision.trigger_price,
        "target_recovery_percent": decision.target_recovery_percent,
        "execution_drift_percent": decision.execution_drift_percent,
        "execution_ceiling": decision.maximum_execution_price,
    }
    if "actual_fill_price" in inputs:
        actual["execution_guard_passed"] = inputs["actual_fill_price"] <= float(
            decision.maximum_execution_price or 0.0
        )
    if "current_price" in inputs:
        actual["decision_reason"] = {
            "waiting_for_atr_spacing": "waiting_for_atr_spacing",
            "recovery_trigger_matched": "trigger_reached",
        }.get(
            decision.reason_code,
            decision.reason_code,
        )
    return actual


def test_golden_fixture_has_supported_schema_and_sanitized_provenance() -> None:
    golden = _load_golden_fixture()

    assert golden["schema_version"] == 1
    assert golden["captured_from"]["source_commit"]
    serialized = json.dumps(golden)
    assert "RE/USDC" not in serialized
    assert "8c93bb24-713f-452f-928b-efbc2e4c8aa3" not in serialized


@pytest.mark.parametrize(
    "case",
    _load_golden_fixture()["static_cases"],
    ids=lambda case: case["name"],
)
def test_static_dca_matches_golden_decisions(case: dict[str, Any]) -> None:
    inputs = case["input"]
    context = build_dca_evaluation_context(
        trade={
            "symbol": "GOLDEN/USDC",
            "deal_id": "golden-deal",
            "execution_count": inputs["safety_orders_count"] + 1,
            "safetyorders_count": inputs["safety_orders_count"],
        },
        config={"dry_run": True},
        current_price=1.0,
        decision_timestamp_ms=0,
        persisted_policy=RecoverySizingPolicy(),
        replay_identity=case["name"],
    )
    decision = evaluate_static_dca_decision(
        context,
        total_pnl=inputs["total_pnl"],
        step_scale=inputs["step_scale"],
        price_deviation=inputs["price_deviation"],
        safety_orders_count=inputs["safety_orders_count"],
    )

    _assert_expected_values(
        {
            "max_deviation": decision.max_deviation,
            "actual_deviation": decision.actual_deviation,
            "should_place": decision.should_place,
            "trigger_threshold": decision.trigger_threshold,
            "next_so_percentage": decision.next_so_percentage,
        },
        case["expected"],
        case_name=case["name"],
    )


@pytest.mark.parametrize(
    "case",
    _load_golden_fixture()["live_recovery_cases"],
    ids=lambda case: case["name"],
)
def test_live_recovery_history_matches_golden_decisions(
    case: dict[str, Any],
) -> None:
    golden = _load_golden_fixture()
    policy = RecoverySizingPolicy.from_dict(golden["recovery_policy"])

    _assert_expected_values(
        _evaluate_live_recovery_case(case, policy),
        case["expected"],
        case_name=case["name"],
    )


@pytest.mark.parametrize(
    "case",
    _load_golden_fixture()["recovery_sizing_cases"],
    ids=lambda case: case["name"],
)
def test_recovery_sizing_matches_golden_decisions(case: dict[str, Any]) -> None:
    golden = _load_golden_fixture()
    policy_values = {
        **golden["recovery_policy"],
        **case.get("policy_overrides", {}),
    }
    result = calculate_recovery_sizing(
        **case["input"],
        policy=RecoverySizingPolicy.from_dict(policy_values),
    )

    _assert_expected_values(
        result.to_dict(),
        case["expected"],
        case_name=case["name"],
    )


def test_live_execution_history_reconstructs_trade_totals() -> None:
    history = _load_golden_fixture()["live_execution_history"]
    expected = history["expected"]
    total_quote = sum(order["quote"] for order in history["orders"])
    total_amount = sum(order["amount"] for order in history["orders"])
    average = total_quote * (1 + history["fee_ratio"]) / total_amount
    take_profit_price = average * (1 + history["take_profit_percent"] / 100)

    assert total_quote == pytest.approx(expected["total_quote"])
    assert total_amount == pytest.approx(expected["total_amount"])
    assert average == pytest.approx(expected["fee_adjusted_average"])
    assert take_profit_price == pytest.approx(expected["take_profit_price"])
    assert history["candles"] == {
        "count": 374,
        "gap_count": 0,
        "duplicate_time_count": 0,
        "invalid_ohlc_count": 0,
        "indicator_source": "execution_ledger",
        "indicator_points": 374,
    }


def test_golden_comparator_rejects_a_deliberate_behavior_mismatch() -> None:
    golden = _load_golden_fixture()
    policy = RecoverySizingPolicy.from_dict(golden["recovery_policy"])
    case = copy.deepcopy(golden["live_recovery_cases"][0])
    case["expected"]["spacing_percent"] += 0.01

    with pytest.raises(AssertionError, match="spacing_percent changed"):
        _assert_expected_values(
            _evaluate_live_recovery_case(case, policy),
            case["expected"],
            case_name=case["name"],
        )
