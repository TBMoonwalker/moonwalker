"""Query-shape and performance coverage for AI trust analytics."""

from __future__ import annotations

import math
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import model
import pytest
import service.ai_trust as ai_trust
import service.ai_trust_analytics as ai_trust_analytics
from tortoise import Tortoise

PRODUCTION_SHAPED_ROW_COUNT = 5000
ANALYTICS_P95_BUDGET_SECONDS = 0.5


class _FakeConfigService:
    def snapshot(self) -> dict[str, Any]:
        return {
            "ai_trust_enabled": True,
            "ai_trust_ollama_model": "qwen3:8b",
        }


class _FakeConfig:
    @classmethod
    async def instance(cls) -> _FakeConfigService:
        return _FakeConfigService()


async def _init_db(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'analytics.sqlite'}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()
    ai_trust_analytics._clear_memory_cache()
    monkeypatch.setattr(ai_trust, "Config", _FakeConfig)


def _prediction(index: int) -> model.AiTrustPrediction:
    closed = index % 4 != 0
    scored = index % 5 != 0
    warned = scored and index % 3 == 0
    bad_entry = closed and index % 7 < 3
    return model.AiTrustPrediction(
        symbol=("BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT")[index % 4],
        deal_id=f"production-{index}",
        source_event="open_deal",
        status="scored" if scored else "unscored",
        provider_status=(
            "scored" if scored else ("timeout" if index % 2 else "disabled")
        ),
        risk_score=index % 101 if scored else None,
        confidence=0.78 if scored else None,
        would_warn=warned if scored else None,
        warning_severity="high" if warned else "none",
        reason_codes_json=('["late_entry","weak_bounce"]' if scored else "[]"),
        outcome_status="closed" if closed else "open",
        bad_entry=bad_entry if closed else None,
        bad_entry_reasons_json=('["non_positive_profit"]' if bad_entry else "[]"),
        outcome_profit=-1.0 if bad_entry else 1.0 if closed else None,
        outcome_profit_percent=-2.0 if bad_entry else 2.0 if closed else None,
        outcome_duration_hours=96.0 if bad_entry else 12.0 if closed else None,
        outcome_so_count=3 if bad_entry else 0 if closed else None,
    )


async def _seed_production_shaped_rows() -> None:
    await model.AiTrustPrediction.bulk_create(
        [_prediction(index) for index in range(PRODUCTION_SHAPED_ROW_COUNT)],
        batch_size=500,
    )
    await ai_trust_analytics.bump_analytics_revision()


@pytest.mark.asyncio
async def test_analytics_cold_read_has_six_queries_and_cache_hit_has_one(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        await _init_db(tmp_path, monkeypatch)
        await model.AiTrustPrediction.bulk_create(
            [_prediction(index) for index in range(20)]
        )
        await ai_trust_analytics.bump_analytics_revision()
        connection = Tortoise.get_connection("default")
        original_execute_query = connection.execute_query
        original_execute_query_dict = connection.execute_query_dict
        query_count = 0

        async def count_execute_query(*args: Any, **kwargs: Any) -> Any:
            nonlocal query_count
            query_count += 1
            return await original_execute_query(*args, **kwargs)

        async def count_execute_query_dict(*args: Any, **kwargs: Any) -> Any:
            nonlocal query_count
            query_count += 1
            return await original_execute_query_dict(*args, **kwargs)

        monkeypatch.setattr(connection, "execute_query", count_execute_query)
        monkeypatch.setattr(
            connection,
            "execute_query_dict",
            count_execute_query_dict,
        )
        ai_trust_analytics._clear_memory_cache()

        cold_payload = await ai_trust.build_analytics_payload()
        cold_query_count = query_count
        cached_payload = await ai_trust.build_analytics_payload()
        cached_query_count = query_count - cold_query_count

        assert cold_payload["coverage"]["total"] == 20
        assert cached_payload == cold_payload
        assert cold_query_count == 6
        assert cached_query_count == 1
    finally:
        ai_trust_analytics._clear_memory_cache()
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_analytics_production_shaped_p95_stays_within_budget(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        await _init_db(tmp_path, monkeypatch)
        await _seed_production_shaped_rows()
        cutoff = datetime.now(UTC) - timedelta(days=180)

        await ai_trust_analytics.load_analytics_rows(
            calibration_cutoff=cutoff,
            calibration_limit=1000,
            recent_limit=12,
            review_limit=12,
        )

        durations: list[float] = []
        payload: dict[str, Any] = {}
        for _ in range(12):
            ai_trust_analytics._clear_memory_cache()
            started_at = time.perf_counter()
            payload = await ai_trust.build_analytics_payload()
            durations.append(time.perf_counter() - started_at)

        p95_index = math.ceil(len(durations) * 0.95) - 1
        p95_seconds = sorted(durations)[p95_index]

        assert payload["coverage"]["total"] == PRODUCTION_SHAPED_ROW_COUNT
        assert payload["calibration"]["closed_samples"] == 1000
        assert len(payload["recent_predictions"]) == 12
        assert len(payload["bad_entry_review"]) <= 12
        assert p95_seconds < ANALYTICS_P95_BUDGET_SECONDS, (
            f"AI analytics p95 {p95_seconds:.3f}s exceeded "
            f"{ANALYTICS_P95_BUDGET_SECONDS:.3f}s"
        )
    finally:
        ai_trust_analytics._clear_memory_cache()
        await Tortoise.close_connections()
