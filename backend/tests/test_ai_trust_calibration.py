"""Focused tests for pure AI trust calibration policy."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from service.ai_trust_calibration import (
    AiTrustCalibrationPolicy,
    build_calibration_payload,
    prediction_to_api,
    rate,
)


def _policy(**overrides: Any) -> AiTrustCalibrationPolicy:
    values = {
        "lookback_days": 180,
        "max_rows": 1000,
        "warming_samples": 10,
        "usable_samples": 30,
        "confident_samples": 75,
        "symbol_usable_samples": 20,
        "bad_entry_rate_floor": 35.0,
        "warning_threshold": 75,
    }
    values.update(overrides)
    return AiTrustCalibrationPolicy(**values)


def _prediction(index: int, **overrides: Any) -> SimpleNamespace:
    values = {
        "id": index,
        "symbol": "ADA/USDT",
        "deal_id": f"deal-{index}",
        "created_at": datetime(2026, 7, 28, tzinfo=UTC),
        "source_event": "open_deal",
        "status": "scored",
        "provider_status": "scored",
        "risk_score": 32,
        "confidence": 0.6,
        "would_warn": index < 15,
        "warning_severity": "low",
        "reason_codes_json": '["weak_bounce"]',
        "operator_note": "AI observed mild risk.",
        "outcome_status": "closed",
        "bad_entry": index < 12,
        "bad_entry_reasons_json": ('["non_positive_profit"]' if index < 12 else "[]"),
        "outcome_profit": -1.0 if index < 12 else 1.0,
        "outcome_profit_percent": -2.0 if index < 12 else 2.0,
        "outcome_duration_hours": 24.0,
        "outcome_so_count": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_calibration_bucket_math_uses_supplied_policy() -> None:
    rows = [_prediction(index) for index in range(30)]

    payload, bucket_index = build_calibration_payload(rows, _policy())

    reason_bucket = bucket_index[("reason_code", "weak_bounce")]
    assert payload["confidence"] == "usable"
    assert payload["closed_samples"] == 30
    assert reason_bucket["bad_entry_rate"] == pytest.approx(40.0)
    assert reason_bucket["warning_hit_rate"] == pytest.approx(80.0)
    assert reason_bucket["false_warning_rate"] == pytest.approx(20.0)
    assert reason_bucket["bad_entry_capture_rate"] == pytest.approx(100.0)
    assert reason_bucket["confidence"] == "usable"
    assert bucket_index[("symbol_reason", "ADA/USDT:weak_bounce")]["usable"] is True


def test_calibration_handles_malformed_lists_and_unexplained_misses() -> None:
    row = _prediction(
        1,
        would_warn=False,
        bad_entry=True,
        reason_codes_json="[not-json",
        bad_entry_reasons_json='{"not": "a-list"}',
    )

    payload, bucket_index = build_calibration_payload([row], _policy())

    assert ("reason_code", "no_reason") in bucket_index
    assert ("bad_entry_reason", "non_positive_profit") not in bucket_index
    assert payload["missed_bad_entry_clusters"] == [
        {
            "symbol": "ADA/USDT",
            "reason_code": "unexplained_ai_miss",
            "missed_bad_entries": 1,
        }
    ]


def test_prediction_presentation_applies_only_usable_calibration_floor() -> None:
    rows = [
        _prediction(index, would_warn=False, bad_entry=index < 15)
        for index in range(30)
    ]
    policy = _policy()
    _, bucket_index = build_calibration_payload(rows, policy)
    open_prediction = _prediction(
        31,
        outcome_status="open",
        bad_entry=None,
        bad_entry_reasons_json="[]",
    )

    payload = prediction_to_api(open_prediction, policy, bucket_index)

    assert payload["risk_score"] == 32
    assert payload["shadow_effective_risk_score"] == 75
    assert payload["calibration_reason"] == "local_bad_entry_rate"
    assert payload["calibration_buckets"]


def test_prediction_presentation_keeps_unscored_rows_unmodified() -> None:
    row = _prediction(
        1,
        risk_score=None,
        created_at=None,
        reason_codes_json='["valid", 42]',
    )

    payload = prediction_to_api(row, _policy(), {})

    assert payload["created_at"] is None
    assert payload["reason_codes"] == ["valid"]
    assert payload["shadow_effective_risk_score"] is None
    assert payload["calibration_reason"] is None
    assert payload["calibration_buckets"] == []
    assert rate(1, 0) == 0.0


def test_calibration_confidence_thresholds_are_configurable() -> None:
    policy = _policy(
        warming_samples=1,
        usable_samples=2,
        confident_samples=3,
        symbol_usable_samples=2,
    )

    payload, bucket_index = build_calibration_payload(
        [_prediction(index) for index in range(3)],
        policy,
    )

    assert payload["confidence"] == "confident"
    assert bucket_index[("reason_code", "weak_bounce")]["confidence"] == "confident"
    assert (
        bucket_index[("symbol_reason", "ADA/USDT:weak_bounce")]["confidence"]
        == "confident"
    )
