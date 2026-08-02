"""Pure calibration policy and presentation helpers for AI trust analytics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, Sequence


class CalibrationPrediction(Protocol):
    """Structural contract required by the calibration read model."""

    id: int
    symbol: str
    deal_id: str | None
    created_at: datetime | None
    source_event: str
    status: str
    provider_status: str
    risk_score: int | None
    confidence: float | None
    would_warn: bool | None
    warning_severity: str
    reason_codes_json: str | None
    operator_note: str | None
    outcome_status: str
    bad_entry: bool | None
    bad_entry_reasons_json: str | None
    outcome_profit: float | None
    outcome_profit_percent: float | None
    outcome_duration_hours: float | None
    outcome_so_count: int | None


@dataclass(frozen=True)
class AiTrustCalibrationPolicy:
    """Thresholds governing read-only AI trust calibration diagnostics."""

    lookback_days: int
    max_rows: int
    warming_samples: int
    usable_samples: int
    confident_samples: int
    symbol_usable_samples: int
    bad_entry_rate_floor: float
    warning_threshold: int


CalibrationBucketIndex = dict[tuple[str, str], dict[str, Any]]


def _safe_int(value: Any) -> int:
    """Return an integer for mixed aggregate values."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    """Return a finite-enough float for mixed aggregate values."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_json_list(value: str | None) -> list[str]:
    """Parse a JSON list of strings from the prediction ledger."""
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]


def _score_band(value: int | None) -> str:
    """Return a stable score-band bucket for calibration."""
    if value is None:
        return "unscored"
    lower = max(0, min(100, (value // 20) * 20))
    upper = 100 if lower >= 100 else min(100, lower + 19)
    return f"{lower}-{upper}"


def _calibration_confidence(
    sample_count: int,
    policy: AiTrustCalibrationPolicy,
    *,
    symbol_specific: bool = False,
) -> str:
    """Return the confidence label for a calibration sample count."""
    if symbol_specific and sample_count < policy.symbol_usable_samples:
        if sample_count < policy.warming_samples:
            return "cold"
        return "warming"
    if sample_count >= policy.confident_samples:
        return "confident"
    if sample_count >= policy.usable_samples:
        return "usable"
    if sample_count >= policy.warming_samples:
        return "warming"
    return "cold"


def _confidence_rank(value: str) -> int:
    """Return ordering rank for calibration confidence labels."""
    return {"cold": 0, "warming": 1, "usable": 2, "confident": 3}.get(value, 0)


def rate(numerator: int, denominator: int) -> float:
    """Return a rounded percentage rate."""
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


def _empty_bucket(bucket_type: str, bucket_key: str) -> dict[str, Any]:
    """Create a mutable calibration bucket accumulator."""
    return {
        "bucket_type": bucket_type,
        "bucket_key": bucket_key,
        "sample_count": 0,
        "closed_count": 0,
        "bad_entry_count": 0,
        "warned_count": 0,
        "warning_hit_count": 0,
        "false_warning_count": 0,
        "bad_entry_capture_count": 0,
    }


def _add_row_to_bucket(
    bucket: dict[str, Any],
    row: CalibrationPrediction,
) -> None:
    """Accumulate closed prediction outcome metrics into one bucket."""
    would_warn = bool(row.would_warn)
    bad_entry = bool(row.bad_entry)
    bucket["sample_count"] += 1
    bucket["closed_count"] += 1
    if bad_entry:
        bucket["bad_entry_count"] += 1
    if would_warn:
        bucket["warned_count"] += 1
    if would_warn and bad_entry:
        bucket["warning_hit_count"] += 1
        bucket["bad_entry_capture_count"] += 1
    if would_warn and not bad_entry:
        bucket["false_warning_count"] += 1


def _finalize_bucket(
    bucket: dict[str, Any],
    policy: AiTrustCalibrationPolicy,
) -> dict[str, Any]:
    """Return the API-safe immutable form of a calibration bucket."""
    closed_count = _safe_int(bucket.get("closed_count"))
    warned_count = _safe_int(bucket.get("warned_count"))
    bad_entry_count = _safe_int(bucket.get("bad_entry_count"))
    confidence = _calibration_confidence(
        closed_count,
        policy,
        symbol_specific=bucket.get("bucket_type") == "symbol_reason",
    )
    return {
        **bucket,
        "bad_entry_rate": rate(bad_entry_count, closed_count),
        "warning_hit_rate": rate(
            _safe_int(bucket.get("warning_hit_count")),
            warned_count,
        ),
        "false_warning_rate": rate(
            _safe_int(bucket.get("false_warning_count")),
            warned_count,
        ),
        "bad_entry_capture_rate": rate(
            _safe_int(bucket.get("bad_entry_capture_count")),
            bad_entry_count,
        ),
        "confidence": confidence,
        "usable": _confidence_rank(confidence) >= _confidence_rank("usable"),
    }


def _prediction_bucket_keys(
    row: CalibrationPrediction,
) -> list[tuple[str, str]]:
    """Return calibration bucket keys for one scored prediction row."""
    reason_codes = _parse_json_list(row.reason_codes_json)
    keys = [
        ("score_band", _score_band(row.risk_score)),
        ("severity", row.warning_severity or "none"),
        ("source_event", row.source_event or "unknown"),
    ]
    for reason_code in reason_codes:
        keys.append(("reason_code", reason_code))
        keys.append(("symbol_reason", f"{row.symbol}:{reason_code}"))
    if not reason_codes:
        keys.append(("reason_code", "no_reason"))
    for reason in _parse_json_list(row.bad_entry_reasons_json):
        keys.append(("bad_entry_reason", reason))
    return keys


def _calibrated_floor_from_bucket(
    bucket: dict[str, Any],
    policy: AiTrustCalibrationPolicy,
) -> int | None:
    """Return a conservative floor for buckets with enough bad-entry signal."""
    if not bucket.get("usable"):
        return None
    if _safe_float(bucket.get("bad_entry_rate")) < policy.bad_entry_rate_floor:
        return None
    return policy.warning_threshold


def build_calibration_payload(
    rows: Sequence[CalibrationPrediction],
    policy: AiTrustCalibrationPolicy,
) -> tuple[dict[str, Any], CalibrationBucketIndex]:
    """Build read-only calibration diagnostics from bounded closed rows."""
    buckets: CalibrationBucketIndex = {}
    missed_clusters: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        for bucket_type, bucket_key in _prediction_bucket_keys(row):
            bucket_id = (bucket_type, bucket_key)
            bucket = buckets.setdefault(
                bucket_id,
                _empty_bucket(bucket_type, bucket_key),
            )
            _add_row_to_bucket(bucket, row)

        if bool(row.bad_entry) and not bool(row.would_warn):
            reason_codes = _parse_json_list(row.reason_codes_json) or [
                "unexplained_ai_miss"
            ]
            for reason_code in reason_codes:
                cluster_id = (row.symbol, reason_code)
                cluster = missed_clusters.setdefault(
                    cluster_id,
                    {
                        "symbol": row.symbol,
                        "reason_code": reason_code,
                        "missed_bad_entries": 0,
                    },
                )
                cluster["missed_bad_entries"] += 1

    finalized = [_finalize_bucket(bucket, policy) for bucket in buckets.values()]
    finalized.sort(
        key=lambda item: (
            _confidence_rank(str(item.get("confidence"))),
            _safe_float(item.get("bad_entry_rate")),
            _safe_int(item.get("closed_count")),
        ),
        reverse=True,
    )
    best_confidence = "cold"
    for bucket in finalized:
        confidence = str(bucket.get("confidence") or "cold")
        if _confidence_rank(confidence) > _confidence_rank(best_confidence):
            best_confidence = confidence

    clusters = list(missed_clusters.values())
    clusters.sort(
        key=lambda item: _safe_int(item.get("missed_bad_entries")),
        reverse=True,
    )
    bucket_index = {
        (str(bucket["bucket_type"]), str(bucket["bucket_key"])): bucket
        for bucket in finalized
    }
    return (
        {
            "enabled": True,
            "confidence": best_confidence,
            "confidence_thresholds": {
                "warming": policy.warming_samples,
                "usable": policy.usable_samples,
                "confident": policy.confident_samples,
                "symbol_usable": policy.symbol_usable_samples,
            },
            "lookback_days": policy.lookback_days,
            "sample_cap": policy.max_rows,
            "closed_samples": len(rows),
            "shadow_effective_warning_threshold": policy.warning_threshold,
            "buckets": finalized[:12],
            "missed_bad_entry_clusters": clusters[:8],
        },
        bucket_index,
    )


def _shadow_effective_risk_for_prediction(
    row: CalibrationPrediction,
    bucket_index: CalibrationBucketIndex,
    policy: AiTrustCalibrationPolicy,
) -> dict[str, Any]:
    """Return derived calibration diagnostics for one prediction row."""
    raw_score = row.risk_score
    if raw_score is None:
        return {
            "shadow_effective_risk_score": None,
            "calibration_reason": None,
            "calibration_buckets": [],
        }
    matched_buckets: list[dict[str, Any]] = []
    calibrated_floor: int | None = None
    for bucket_type, bucket_key in _prediction_bucket_keys(row):
        bucket = bucket_index.get((bucket_type, bucket_key))
        if bucket is None:
            continue
        floor = _calibrated_floor_from_bucket(bucket, policy)
        if floor is None:
            continue
        matched_buckets.append(
            {
                "bucket_type": bucket_type,
                "bucket_key": bucket_key,
                "bad_entry_rate": bucket["bad_entry_rate"],
                "closed_count": bucket["closed_count"],
                "confidence": bucket["confidence"],
            }
        )
        calibrated_floor = max(calibrated_floor or raw_score, floor)
    effective_score = max(raw_score, calibrated_floor or raw_score)
    return {
        "shadow_effective_risk_score": effective_score,
        "calibration_reason": (
            "local_bad_entry_rate"
            if effective_score > raw_score and matched_buckets
            else None
        ),
        "calibration_buckets": matched_buckets[:4],
    }


def prediction_to_api(
    row: CalibrationPrediction,
    policy: AiTrustCalibrationPolicy,
    bucket_index: CalibrationBucketIndex | None = None,
) -> dict[str, Any]:
    """Return a compact API representation of a prediction row."""
    payload = {
        "id": row.id,
        "symbol": row.symbol,
        "deal_id": row.deal_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "source_event": row.source_event,
        "status": row.status,
        "provider_status": row.provider_status,
        "risk_score": row.risk_score,
        "confidence": row.confidence,
        "would_warn": row.would_warn,
        "warning_severity": row.warning_severity,
        "reason_codes": _parse_json_list(row.reason_codes_json),
        "operator_note": row.operator_note,
        "outcome_status": row.outcome_status,
        "bad_entry": row.bad_entry,
        "bad_entry_reasons": _parse_json_list(row.bad_entry_reasons_json),
        "outcome_profit": row.outcome_profit,
        "outcome_profit_percent": row.outcome_profit_percent,
        "outcome_duration_hours": row.outcome_duration_hours,
        "outcome_so_count": row.outcome_so_count,
    }
    if bucket_index is not None:
        payload.update(
            _shadow_effective_risk_for_prediction(
                row,
                bucket_index,
                policy,
            )
        )
    return payload
