"""Bounded database read model and cache for AI trust analytics."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import model
from tortoise import Tortoise
from tortoise.expressions import Q


@dataclass(frozen=True)
class AiTrustAnalyticsRows:
    """Reduced counts and bounded detail rows used by the analytics facade."""

    counts: dict[str, int]
    provider_counts: dict[str, int]
    calibration: tuple[model.AiTrustPrediction, ...]
    recent: tuple[model.AiTrustPrediction, ...]
    review: tuple[model.AiTrustPrediction, ...]


_cached_revision: str | None = None
_cached_rows: AiTrustAnalyticsRows | None = None


def _clear_memory_cache() -> None:
    """Discard the process-local analytics read model."""
    global _cached_revision
    global _cached_rows
    _cached_revision = None
    _cached_rows = None


async def bump_analytics_revision() -> None:
    """Persist a new invalidation token after an analytics-visible write."""
    _clear_memory_cache()
    await model.AiTrustAnalyticsRevision.update_or_create(
        id=1,
        defaults={"revision": str(uuid.uuid4())},
    )


async def _revision_token() -> str | None:
    """Return the persisted revision token, if service writes initialized it."""
    row = await model.AiTrustAnalyticsRevision.get_or_none(id=1)
    return row.revision if row is not None else None


async def _aggregate_counts() -> dict[str, int]:
    """Compute analytics counters in one conditional aggregate query."""
    connection = Tortoise.get_connection("default")
    rows = await connection.execute_query_dict("""
        SELECT
            COUNT(*) AS total,
            COUNT(CASE WHEN status = 'scored' THEN 1 END) AS scored,
            COUNT(CASE WHEN outcome_status = 'closed' THEN 1 END) AS closed,
            COUNT(
                CASE WHEN status = 'scored' AND would_warn = TRUE THEN 1 END
            ) AS warnings,
            COUNT(
                CASE
                    WHEN status = 'scored'
                        AND would_warn = TRUE
                        AND outcome_status = 'closed'
                        AND bad_entry = FALSE
                    THEN 1
                END
            ) AS false_warnings,
            COUNT(
                CASE
                    WHEN outcome_status = 'closed' AND bad_entry = TRUE THEN 1
                END
            ) AS bad_entries,
            COUNT(
                CASE
                    WHEN outcome_status = 'closed'
                        AND bad_entry = TRUE
                        AND would_warn = TRUE
                    THEN 1
                END
            ) AS captured_bad_entries
        FROM ai_trust_predictions
        """)
    raw = rows[0] if rows else {}
    return {
        key: int(raw.get(key) or 0)
        for key in (
            "total",
            "scored",
            "closed",
            "warnings",
            "false_warnings",
            "bad_entries",
            "captured_bad_entries",
        )
    }


async def _aggregate_provider_statuses() -> dict[str, int]:
    """Group provider status counts in the database without loading each row."""
    connection = Tortoise.get_connection("default")
    rows = await connection.execute_query_dict("""
        SELECT provider_status, COUNT(*) AS status_count
        FROM ai_trust_predictions
        GROUP BY provider_status
        """)
    return {
        str(row["provider_status"]): int(row["status_count"])
        for row in rows
        if row.get("provider_status") is not None
    }


async def load_analytics_rows(
    *,
    calibration_cutoff: Any,
    calibration_limit: int,
    recent_limit: int,
    review_limit: int,
) -> AiTrustAnalyticsRows:
    """Return aggregate counters and strictly bounded supporting detail rows."""
    global _cached_revision
    global _cached_rows

    revision = await _revision_token()
    if revision is not None and revision == _cached_revision and _cached_rows:
        return _cached_rows

    counts = await _aggregate_counts()
    provider_counts = await _aggregate_provider_statuses()
    calibration = tuple(
        await model.AiTrustPrediction.filter(
            status="scored",
            outcome_status="closed",
            created_at__gte=calibration_cutoff,
        )
        .order_by("-created_at")
        .limit(calibration_limit)
    )
    recent = tuple(
        await model.AiTrustPrediction.all().order_by("-created_at").limit(recent_limit)
    )
    review_candidates = tuple(
        await model.AiTrustPrediction.filter(outcome_status="closed")
        .filter(Q(bad_entry=True) | Q(would_warn=True))
        .order_by("-created_at")
        .limit(review_limit * 2)
    )
    bad_entries = [row for row in review_candidates if row.bad_entry is True]
    selected_ids = {row.id for row in bad_entries[:review_limit]}
    warnings = [
        row
        for row in review_candidates
        if row.would_warn is True and row.id not in selected_ids
    ]
    review = tuple((bad_entries[:review_limit] + warnings)[:review_limit])
    result = AiTrustAnalyticsRows(
        counts=counts,
        provider_counts=provider_counts,
        calibration=calibration,
        recent=recent,
        review=review,
    )
    if revision is not None:
        _cached_revision = revision
        _cached_rows = result
    return result
