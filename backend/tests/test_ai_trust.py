"""Regression coverage for the optional AI trust cockpit."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import model
import pytest
import service.ai_trust as ai_trust
from service.ai_trust import AiTrustResponseError
from tortoise import Tortoise


class _FakeConfigService:
    def __init__(self, snapshot: dict[str, Any]) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> dict[str, Any]:
        return self._snapshot


class _FakeConfig:
    snapshot: dict[str, Any] = {}

    @classmethod
    async def instance(cls) -> _FakeConfigService:
        return _FakeConfigService(cls.snapshot)


async def _init_db(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()


def test_feature_bundle_excludes_secrets_and_raw_payloads() -> None:
    payload = {
        "symbol": "BTC/USDT",
        "deal_id": "deal-1",
        "timestamp": "2026-06-10T12:00:00Z",
        "price": 100.0,
        "amount": 0.2,
        "ordersize": 20.0,
        "fee": 0.01,
        "baseorder": True,
        "secret": "do-not-send",
        "api_key": "do-not-send",
        "raw_ohlcv": [[1, 2, 3, 4, 5]],
        "raw_config": {"tp": 1.5},
    }

    bundle = ai_trust.build_entry_feature_bundle("BTC/USDT", payload)
    serialized = json.dumps(bundle).lower()

    assert "do-not-send" not in serialized
    assert "secret" not in serialized
    assert "api_key" not in serialized
    assert "raw_ohlcv" not in serialized
    assert "raw_config" not in serialized
    assert bundle["position"]["entry_notional"] == pytest.approx(20.0)


def test_validate_ai_trust_output_accepts_valid_schema() -> None:
    result = ai_trust.validate_ai_trust_output(
        json.dumps(
            {
                "risk_score": 72,
                "confidence": 0.81,
                "would_warn": True,
                "warning_severity": "high",
                "reason_codes": ["late_entry", "thin_context"],
                "operator_note": "AI observed elevated entry risk.",
            }
        )
    )

    assert result["risk_score"] == 72
    assert result["confidence"] == pytest.approx(0.81)
    assert result["would_warn"] is True
    assert result["warning_severity"] == "high"


def test_validate_ai_trust_output_accepts_common_ollama_schema_drift() -> None:
    result = ai_trust.validate_ai_trust_output(
        {
            "risk_score": "72",
            "confidence": "0.81",
            "would_warn": "true",
            "warning_severity": "High ",
            "reason_codes": "late_entry, thin_context",
            "operator_note": None,
        }
    )

    assert result == {
        "risk_score": 72,
        "confidence": 0.81,
        "would_warn": True,
        "warning_severity": "high",
        "reason_codes": ["late_entry", "thin_context"],
        "operator_note": "",
    }


def test_validate_ai_trust_output_treats_fractional_risk_as_percent() -> None:
    result = ai_trust.validate_ai_trust_output(
        {
            "risk_score": 0.72,
            "would_warn": True,
            "warning_severity": "medium",
            "operator_note": (
                "Entry occurs during a strong 48-candle downtrend with price "
                "significantly below recent highs."
            ),
        }
    )

    assert result["risk_score"] == 72
    assert result["confidence"] == pytest.approx(0.5)
    assert result["would_warn"] is True
    assert result["warning_severity"] == "medium"
    assert result["reason_codes"] == []


def test_validate_ai_trust_output_accepts_fenced_nested_aliases() -> None:
    result = ai_trust.validate_ai_trust_output("""
        ```json
        {
          "result": {
            "score": "72/100",
            "confidence_score": "81%",
            "warning": "yes",
            "risk_level": "moderate",
            "reasons": [{"code": "late_entry"}, {"reason": "thin_context"}],
            "explanation": ["AI observed elevated risk."]
          }
        }
        ```
        """)

    assert result == {
        "risk_score": 72,
        "confidence": 0.81,
        "would_warn": True,
        "warning_severity": "medium",
        "reason_codes": ["late_entry", "thin_context"],
        "operator_note": "AI observed elevated risk.",
    }


def test_validate_ai_trust_output_derives_optional_warning_fields() -> None:
    result = ai_trust.validate_ai_trust_output(
        {
            "risk": 82,
            "certainty": 0.6,
            "reason": {"primary": "volatile_entry"},
        }
    )

    assert result["risk_score"] == 82
    assert result["would_warn"] is True
    assert result["warning_severity"] == "high"
    assert result["reason_codes"] == ["volatile_entry"]


def test_validate_ai_trust_output_normalizes_score_warning_consistency() -> None:
    result = ai_trust.validate_ai_trust_output(
        {
            "risk_score": 1,
            "confidence": 0.5,
            "would_warn": True,
            "warning_severity": "high",
            "reason_codes": ["model_inconsistent"],
            "operator_note": "AI observed high risk.",
        }
    )

    assert result["risk_score"] == 1
    assert result["would_warn"] is False
    assert result["warning_severity"] == "none"


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        {"risk_score": 101, "confidence": 0.5},
        {
            "risk_score": 50,
            "confidence": 1.2,
            "would_warn": False,
            "warning_severity": "none",
            "reason_codes": [],
            "operator_note": "AI observed.",
        },
        {
            "risk_score": 50,
            "confidence": 0.5,
            "would_warn": "maybe",
            "warning_severity": "none",
            "reason_codes": [],
            "operator_note": "AI observed.",
        },
    ],
)
def test_validate_ai_trust_output_rejects_malformed_output(payload: Any) -> None:
    with pytest.raises(AiTrustResponseError):
        ai_trust.validate_ai_trust_output(payload)


@pytest.mark.asyncio
async def test_ollama_request_bounds_generation_and_disables_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    debug_messages: list[tuple[str, str]] = []
    raw_content = json.dumps(
        {
            "risk_score": 25,
            "confidence": 0.5,
            "would_warn": False,
            "warning_severity": "none",
            "reason_codes": [],
            "operator_note": "AI observed normal entry risk.",
        }
    )

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"message": {"content": raw_content}}

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
            captured["url"] = url
            captured["payload"] = json
            return _FakeResponse()

    monkeypatch.setattr(ai_trust.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        ai_trust.logging,
        "debug",
        lambda message, value: debug_messages.append((message, value)),
    )

    result = await ai_trust._call_ollama(
        ai_trust.AiTrustConfig(
            enabled=True,
            enforce_warnings=False,
            ollama_base_url="http://ollama.local:11434",
            ollama_model="qwen3:8b",
            timeout_ms=60000,
            max_retries=0,
        ),
        {"schema_version": "1", "source_event": "open_deal"},
    )

    payload = captured["payload"]
    assert captured["url"] == "http://ollama.local:11434/api/chat"
    assert captured["timeout"] == pytest.approx(60.0)
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"]["temperature"] == 0
    assert payload["options"]["num_predict"] == ai_trust.OLLAMA_RESPONSE_NUM_PREDICT
    assert result["risk_score"] == 25
    assert debug_messages == [
        ("AI trust provider raw response content: %s", raw_content)
    ]


def test_truncate_provider_debug_text_limits_raw_response_length() -> None:
    raw_content = "x" * (ai_trust.OLLAMA_DEBUG_RESPONSE_MAX_CHARS + 10)

    result = ai_trust._truncate_provider_debug_text(raw_content)

    assert result.endswith("...<truncated>")
    assert len(result) == (
        ai_trust.OLLAMA_DEBUG_RESPONSE_MAX_CHARS + len("...<truncated>")
    )


@pytest.mark.asyncio
async def test_disabled_ai_trust_does_not_record_predictions(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        await _init_db(tmp_path, monkeypatch)
        _FakeConfig.snapshot = {
            "ai_trust_enabled": False,
            "ai_trust_ollama_model": "qwen3:8b",
        }
        monkeypatch.setattr(ai_trust, "Config", _FakeConfig)

        await ai_trust.observe_new_deal(
            "BTC/USDT",
            {"symbol": "BTC/USDT", "deal_id": "deal-1", "price": 100.0},
        )

        assert await model.AiTrustPrediction.all().count() == 0
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_enrich_entry_feature_bundle_adds_derived_market_context(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        await _init_db(tmp_path, monkeypatch)
        for index in range(1, 25):
            close = 100 + index
            await model.Tickers.create(
                timestamp=str(1_000_000 + index),
                symbol="BTC/USDT",
                open=close - 1,
                high=close + 2,
                low=close - 2,
                close=close,
                volume=1000 + index,
            )

        bundle = ai_trust.build_entry_feature_bundle(
            "BTC/USDT",
            {
                "symbol": "BTC/USDT",
                "deal_id": "deal-1",
                "price": 124.0,
                "amount": 0.1,
                "ordersize": 12.4,
                "baseorder": True,
                "timeframe": "5m",
                "raw_ohlcv": [[1, 2, 3, 4, 5]],
            },
        )
        enriched = await ai_trust.enrich_entry_feature_bundle(bundle)

        serialized = json.dumps(enriched).lower()
        assert "raw_ohlcv" not in serialized
        assert enriched["domain_context"] == {
            "market": "crypto",
            "instrument_type": "spot_pair",
            "base_asset": "BTC",
            "quote_asset": "USDT",
            "strategy_family": "dca_entry_observation",
        }
        assert enriched["market_context"]["has_market_context"] is True
        assert enriched["market_context"]["candle_count"] == 24
        assert enriched["market_context"]["timeframe_minutes"] == 5
        assert enriched["market_context"]["change_pct_3_candles"] is not None
        assert (
            enriched["market_context"]["realized_volatility_pct_20_candles"] is not None
        )
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_missing_ollama_model_records_unscored_prediction(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        await _init_db(tmp_path, monkeypatch)
        _FakeConfig.snapshot = {
            "ai_trust_enabled": True,
            "ai_trust_ollama_base_url": "http://localhost:11434",
            "ai_trust_ollama_model": "",
            "ai_trust_timeout_ms": 2500,
            "ai_trust_max_retries": 0,
        }
        monkeypatch.setattr(ai_trust, "Config", _FakeConfig)

        await ai_trust.observe_new_deal(
            "BTC/USDT",
            {
                "symbol": "BTC/USDT",
                "deal_id": "deal-1",
                "timestamp": "2026-06-10T12:00:00Z",
                "price": 100.0,
                "amount": 0.2,
                "ordersize": 20.0,
                "baseorder": True,
            },
        )

        row = await model.AiTrustPrediction.get(deal_id="deal-1")
        assert row.status == "unscored"
        assert row.provider_status == ai_trust.PROVIDER_STATUS_MISSING_MODEL
        assert row.risk_score is None
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_provider_output_records_scored_prediction(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        await _init_db(tmp_path, monkeypatch)
        _FakeConfig.snapshot = {
            "ai_trust_enabled": True,
            "ai_trust_ollama_base_url": "http://localhost:11434",
            "ai_trust_ollama_model": "qwen3:8b",
            "ai_trust_timeout_ms": 2500,
            "ai_trust_max_retries": 0,
        }
        monkeypatch.setattr(ai_trust, "Config", _FakeConfig)

        async def fake_score(_trust_config: Any, _feature_bundle: dict[str, Any]):
            return ai_trust.PROVIDER_STATUS_SCORED, {
                "risk_score": 64,
                "confidence": 0.7,
                "would_warn": True,
                "warning_severity": "medium",
                "reason_codes": ["extended_entry"],
                "operator_note": "AI observed elevated risk.",
            }

        monkeypatch.setattr(ai_trust, "_score_with_provider", fake_score)

        await ai_trust.observe_new_deal(
            "ETH/USDT",
            {"symbol": "ETH/USDT", "deal_id": "deal-2", "price": 120.0},
        )

        row = await model.AiTrustPrediction.get(deal_id="deal-2")
        assert row.status == "scored"
        assert row.provider_status == ai_trust.PROVIDER_STATUS_SCORED
        assert row.risk_score == 64
        assert row.would_warn is True
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_entry_enforcement_blocks_scored_warning_and_records_ledger(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        await _init_db(tmp_path, monkeypatch)

        async def fake_score(_trust_config: Any, _feature_bundle: dict[str, Any]):
            return ai_trust.PROVIDER_STATUS_SCORED, {
                "risk_score": 78,
                "confidence": 0.82,
                "would_warn": True,
                "warning_severity": "high",
                "reason_codes": ["strong_downtrend"],
                "operator_note": "AI observed elevated entry risk.",
            }

        monkeypatch.setattr(ai_trust, "_score_with_provider", fake_score)

        gate = await ai_trust.evaluate_entry_enforcement(
            "BTC/USDT",
            {
                "symbol": "BTC/USDT",
                "ordersize": 50.0,
                "current_price": 100.0,
                "baseorder": True,
                "safetyorder": False,
                "ordertype": "market",
                "side": "buy",
            },
            {
                "ai_trust_enabled": True,
                "ai_trust_enforce_warnings": True,
                "ai_trust_ollama_base_url": "http://localhost:11434",
                "ai_trust_ollama_model": "qwen3:8b",
                "ai_trust_timeout_ms": 2500,
                "ai_trust_max_retries": 0,
            },
        )

        assert gate.allowed is False
        assert gate.reason_code == "ai_trust_warning"
        assert gate.risk_score == 78

        row = await model.AiTrustPrediction.get(symbol="BTC/USDT")
        assert row.source_event == "entry_blocked"
        assert row.outcome_status == "blocked"
        assert row.status == "scored"
        assert row.risk_score == 78
        assert row.would_warn is True
        assert json.loads(row.reason_codes_json) == ["strong_downtrend"]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_entry_enforcement_fail_blocks_unscored_provider_status(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        await _init_db(tmp_path, monkeypatch)

        async def fake_score(_trust_config: Any, _feature_bundle: dict[str, Any]):
            return ai_trust.PROVIDER_STATUS_TIMEOUT, None

        monkeypatch.setattr(ai_trust, "_score_with_provider", fake_score)

        gate = await ai_trust.evaluate_entry_enforcement(
            "ETH/USDT",
            {
                "symbol": "ETH/USDT",
                "ordersize": 50.0,
                "current_price": 100.0,
                "baseorder": True,
                "safetyorder": False,
            },
            {
                "ai_trust_enabled": True,
                "ai_trust_enforce_warnings": True,
                "ai_trust_ollama_model": "qwen3:8b",
            },
        )

        assert gate.allowed is False
        assert gate.reason_code == "ai_trust_unavailable"
        assert gate.provider_status == ai_trust.PROVIDER_STATUS_TIMEOUT

        row = await model.AiTrustPrediction.get(symbol="ETH/USDT")
        assert row.source_event == "entry_blocked"
        assert row.outcome_status == "blocked"
        assert row.status == "unscored"
        assert row.provider_status == ai_trust.PROVIDER_STATUS_TIMEOUT

        runtime_status = await model.AppConfig.get(
            key=ai_trust.AI_TRUST_RUNTIME_STATUS_KEY
        )
        runtime_provider_status = await model.AppConfig.get(
            key=ai_trust.AI_TRUST_RUNTIME_PROVIDER_STATUS_KEY
        )
        assert (
            runtime_status.value
            == ai_trust.AI_TRUST_RUNTIME_STATUS_PROVIDER_UNAVAILABLE
        )
        assert runtime_provider_status.value == ai_trust.PROVIDER_STATUS_TIMEOUT
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_outcome_attribution_labels_bad_entries(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        await _init_db(tmp_path, monkeypatch)
        now = datetime.now(UTC)
        await model.AiTrustPrediction.create(
            symbol="SOL/USDT",
            deal_id="deal-3",
            source_event="open_deal",
            status="scored",
            provider_status="scored",
            risk_score=80,
            confidence=0.8,
            would_warn=True,
            warning_severity="high",
            reason_codes_json='["slow_setup"]',
        )
        await model.ClosedTrades.create(
            symbol="SOL/USDT",
            deal_id="deal-3",
            profit=0.0,
            profit_percent=0.0,
            so_count=3,
            open_date=(now - timedelta(hours=96)).isoformat(),
            close_date=now.isoformat(),
            duration="4 days, 0:00:00",
        )

        await ai_trust.attribute_closed_outcome("deal-3")

        row = await model.AiTrustPrediction.get(deal_id="deal-3")
        reasons = json.loads(row.bad_entry_reasons_json)
        assert row.outcome_status == "closed"
        assert row.bad_entry is True
        assert "non_positive_profit" in reasons
        assert "slow_close" in reasons
        assert "safety_order_heavy" in reasons
    finally:
        await Tortoise.close_connections()
