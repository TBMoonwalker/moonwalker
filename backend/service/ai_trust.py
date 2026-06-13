"""Shadow-mode AI trust scoring and calibration service."""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import helper
import httpx
import model
from service.config import Config

logging = helper.LoggerFactory.get_logger("logs/ai_trust.log", "ai_trust")

PROMPT_VERSION = "ai_trust_v1"
SCHEMA_VERSION = "1"
PROVIDER_NAME = "ollama"
BAD_ENTRY_SLOW_HOURS = 72.0
BAD_ENTRY_HEAVY_SAFETY_ORDERS = 3
MAX_RECENT_PREDICTIONS = 12
MAX_BAD_ENTRY_REVIEW = 12
OLLAMA_RESPONSE_NUM_PREDICT = 384
OLLAMA_DEBUG_RESPONSE_MAX_CHARS = 4000
AI_TRUST_OUTPUT_FIELDS = {
    "risk_score",
    "confidence",
    "would_warn",
    "warning_severity",
    "reason_codes",
    "operator_note",
}
AI_TRUST_FIELD_ALIASES = {
    "risk_score": (
        "risk_score",
        "risk",
        "score",
        "entry_risk_score",
        "bad_entry_risk_score",
        "bad_entry_risk",
    ),
    "confidence": ("confidence", "confidence_score", "certainty"),
    "would_warn": (
        "would_warn",
        "warn",
        "warning",
        "ai_would_warn",
        "should_warn",
    ),
    "warning_severity": (
        "warning_severity",
        "severity",
        "warning_level",
        "risk_level",
    ),
    "reason_codes": ("reason_codes", "reasons", "reason_code", "reason"),
    "operator_note": ("operator_note", "note", "explanation", "rationale"),
}
WARNING_SEVERITY_ALIASES = {
    "no": "none",
    "normal": "none",
    "minimal": "low",
    "minor": "low",
    "moderate": "medium",
    "med": "medium",
    "elevated": "medium",
    "severe": "high",
    "critical": "high",
}

WARNING_SEVERITIES = {"none", "low", "medium", "high"}
PROVIDER_STATUS_DISABLED = "disabled"
PROVIDER_STATUS_MISSING_MODEL = "missing_model"
PROVIDER_STATUS_SCORED = "scored"
PROVIDER_STATUS_TIMEOUT = "timeout"
PROVIDER_STATUS_CONNECTION_ERROR = "connection_error"
PROVIDER_STATUS_PROVIDER_ERROR = "provider_error"
PROVIDER_STATUS_MALFORMED_JSON = "malformed_json"
PROVIDER_STATUS_SCHEMA_INVALID = "schema_invalid"
PROVIDER_STATUS_UNEXPECTED_ERROR = "unexpected_error"
AI_TRUST_RUNTIME_STATUS_KEY = "ai_trust_runtime_status"
AI_TRUST_RUNTIME_PROVIDER_STATUS_KEY = "ai_trust_runtime_provider_status"
AI_TRUST_RUNTIME_UPDATED_AT_KEY = "ai_trust_runtime_updated_at"
AI_TRUST_RUNTIME_STATUS_OK = "ok"
AI_TRUST_RUNTIME_STATUS_PROVIDER_UNAVAILABLE = "provider_unavailable"
AI_TRUST_RUNTIME_STATUS_WARNING_BLOCKED = "warning_blocked"

AI_TRUST_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "risk_score": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "description": "Integer risk score from 0 to 100; do not return 0..1.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Model confidence from 0.0 to 1.0.",
        },
        "would_warn": {
            "type": "boolean",
            "description": "Whether the AI would have warned the operator.",
        },
        "warning_severity": {
            "type": "string",
            "enum": ["none", "low", "medium", "high"],
        },
        "reason_codes": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
        "operator_note": {"type": "string", "maxLength": 240},
    },
    "required": [
        "risk_score",
        "confidence",
        "would_warn",
        "warning_severity",
        "reason_codes",
        "operator_note",
    ],
}


@dataclass(frozen=True)
class AiTrustConfig:
    """Runtime configuration for the optional AI trust service."""

    enabled: bool
    enforce_warnings: bool
    ollama_base_url: str
    ollama_model: str
    timeout_ms: int
    max_retries: int


@dataclass(frozen=True)
class AiTrustEntryGate:
    """Decision returned by optional AI entry enforcement."""

    allowed: bool
    evaluated: bool
    provider_status: str
    reason_code: str | None = None
    risk_score: int | None = None
    warning_severity: str = "none"
    operator_note: str | None = None


class AiTrustResponseError(ValueError):
    """Raised when a provider response cannot become a prediction."""


def _safe_bool(value: Any) -> bool:
    """Convert mixed config values into a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _safe_int(value: Any, default: int = 0) -> int:
    """Convert a value into an integer with a bounded fallback."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value into a finite float with a fallback."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    """Round finite numbers while preserving missing values."""
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _pct_change(current: float, previous: float | None) -> float | None:
    """Return percentage change between two positive prices."""
    if previous is None or previous <= 0:
        return None
    return ((current - previous) / previous) * 100


def _risk_score_severity(risk_score: int) -> str:
    """Map the canonical score to a bounded warning severity."""
    if risk_score >= 70:
        return "high"
    if risk_score >= 45:
        return "medium"
    if risk_score >= 20:
        return "low"
    return "none"


def _severity_rank(severity: str) -> int:
    """Return ordering rank for warning severities."""
    return {"none": 0, "low": 1, "medium": 2, "high": 3}.get(severity, 0)


def _normalize_warning_consistency(
    risk_score: int,
    would_warn: bool,
    warning_severity: str,
) -> tuple[bool, str]:
    """Keep accepted AI output internally consistent with its risk score."""
    score_severity = _risk_score_severity(risk_score)
    if _severity_rank(warning_severity) > _severity_rank(score_severity):
        warning_severity = score_severity
    if warning_severity == "none":
        return False, warning_severity
    if risk_score >= 50:
        return True, warning_severity
    return would_warn, warning_severity


def _coerce_ai_int(value: Any, *, minimum: int, maximum: int) -> int:
    """Coerce local-model risk-score drift while preserving strict bounds."""
    if isinstance(value, bool):
        raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float) and math.isfinite(value):
        parsed = round(value * 100) if 0 < value < 1 else round(value)
    elif isinstance(value, str):
        value = value.strip()
        if value.lower() in WARNING_SEVERITIES:
            return {"none": 0, "low": 25, "medium": 55, "high": 80}[value.lower()]
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if not match:
            raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)
        try:
            numeric = float(match.group(0))
        except ValueError as exc:
            raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID) from exc
        if value.endswith("%"):
            parsed = round(numeric)
        else:
            parsed = round(numeric * 100) if 0 < numeric < 1 else round(numeric)
    else:
        raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)
    if parsed < minimum or parsed > maximum:
        raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)
    return parsed


def _coerce_ai_float(value: Any, *, minimum: float, maximum: float) -> float:
    """Coerce local-model numeric drift while preserving strict bounds."""
    if isinstance(value, bool):
        raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)
    divisor = 1.0
    if isinstance(value, str):
        stripped = value.strip()
        divisor = 100.0 if stripped.endswith("%") else 1.0
        match = re.search(r"-?\d+(?:\.\d+)?", stripped)
        if not match:
            raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)
        value = match.group(0)
    try:
        parsed = float(value) / divisor
    except (TypeError, ValueError) as exc:
        raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID) from exc
    if not math.isfinite(parsed) or parsed < minimum or parsed > maximum:
        raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)
    return parsed


def _coerce_ai_bool(value: Any) -> bool:
    """Coerce common local-model boolean spellings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "warn", "warning", "would_warn"}:
            return True
        if normalized in {"false", "no", "0", "none", "no warning"}:
            return False
    raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)


def _extract_json_object_text(value: str) -> str | None:
    """Extract the first balanced JSON object from model text."""
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False
    for index, char in enumerate(cleaned):
        if in_string:
            escaped = char == "\\" and not escaped
            if char == '"' and not escaped:
                in_string = False
            elif char != "\\":
                escaped = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return cleaned[start : index + 1]
    return None


def _parse_ai_trust_json(raw: Any) -> Any:
    """Parse provider output that may include fences or brief extra text."""
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        extracted = _extract_json_object_text(raw)
        if extracted is None:
            raise AiTrustResponseError(PROVIDER_STATUS_MALFORMED_JSON)
        try:
            return json.loads(extracted)
        except json.JSONDecodeError as exc:
            raise AiTrustResponseError(PROVIDER_STATUS_MALFORMED_JSON) from exc


def _canonical_key(key: str) -> str | None:
    """Return the canonical prediction field for a model-produced key."""
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    for canonical, aliases in AI_TRUST_FIELD_ALIASES.items():
        if normalized in aliases:
            return canonical
    return None


def _normalize_prediction_keys(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize aliases from local models to the provider contract fields."""
    normalized: dict[str, Any] = {}
    for key, field_value in value.items():
        canonical = _canonical_key(str(key))
        if canonical and canonical not in normalized:
            normalized[canonical] = field_value
    for key in AI_TRUST_OUTPUT_FIELDS:
        if key in value and key not in normalized:
            normalized[key] = value[key]
    return normalized


def _find_prediction_object(value: Any) -> dict[str, Any] | None:
    """Find the most prediction-shaped object in a nested provider response."""
    if isinstance(value, dict):
        normalized = _normalize_prediction_keys(value)
        if "risk_score" in normalized:
            return normalized
        for child in value.values():
            found = _find_prediction_object(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_prediction_object(child)
            if found is not None:
                return found
    return None


def _coerce_warning_severity(value: Any, *, risk_score: int) -> str:
    """Normalize severity names, deriving from score when absent."""
    severity = str(value or "").strip().lower()
    severity = WARNING_SEVERITY_ALIASES.get(severity, severity)
    if severity in WARNING_SEVERITIES:
        return severity
    if not severity:
        return _risk_score_severity(risk_score)
    raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)


def _coerce_reason_codes(value: Any) -> list[str]:
    """Normalize reason code shapes produced by local models."""
    if value is None:
        values: list[Any] = []
    elif isinstance(value, str):
        values = re.split(r"[,;\n]+", value)
    elif isinstance(value, dict):
        values = list(value.values())
    elif isinstance(value, list):
        values = value
    else:
        raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)
    if len(values) > 8:
        raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)
    normalized: list[str] = []
    for reason_code in values:
        if isinstance(reason_code, dict):
            reason_code = (
                reason_code.get("code")
                or reason_code.get("reason")
                or reason_code.get("name")
                or reason_code.get("label")
            )
        if reason_code is None:
            continue
        reason = str(reason_code).strip()[:64]
        if reason:
            normalized.append(reason)
    return normalized


def _describe_ai_output_shape(raw: Any) -> str:
    """Describe provider output shape without logging raw model content."""
    raw_type = type(raw).__name__
    try:
        parsed = _parse_ai_trust_json(raw)
    except AiTrustResponseError:
        return f"raw_type={raw_type} parsed_type=unparseable"
    parsed_type = type(parsed).__name__
    if not isinstance(parsed, dict):
        return f"raw_type={raw_type} parsed_type={parsed_type}"
    keys = ",".join(str(key)[:32] for key in parsed.keys())
    prediction = _find_prediction_object(parsed)
    if prediction is None:
        return f"raw_type={raw_type} parsed_type=dict keys={keys}"
    prediction_keys = ",".join(str(key)[:32] for key in prediction.keys())
    prediction_types = ",".join(
        f"{key}:{type(value).__name__}" for key, value in prediction.items()
    )
    return (
        f"raw_type={raw_type} parsed_type=dict keys={keys} "
        f"prediction_keys={prediction_keys} prediction_types={prediction_types}"
    )


def _truncate_provider_debug_text(raw: Any) -> str:
    """Return bounded provider content for debug-only logs."""
    if isinstance(raw, str):
        value = raw
    else:
        try:
            value = json.dumps(raw, sort_keys=True, default=str)
        except (TypeError, ValueError):
            value = str(raw)
    if len(value) <= OLLAMA_DEBUG_RESPONSE_MAX_CHARS:
        return value
    return value[:OLLAMA_DEBUG_RESPONSE_MAX_CHARS] + "...<truncated>"


def _json_dumps(value: Any) -> str:
    """Return stable JSON for persisted feature and reason snapshots."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _now_ms_text() -> str:
    """Return the current UTC timestamp in milliseconds as text."""
    return str(int(datetime.now(UTC).timestamp() * 1000))


def _timeframe_to_minutes(value: Any) -> int | None:
    """Convert common timeframe strings into minutes for derived context."""
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    unit = raw[-1]
    amount = _safe_int(raw[:-1], 0)
    if amount <= 0:
        return None
    if unit == "m":
        return amount
    if unit == "h":
        return amount * 60
    if unit == "d":
        return amount * 60 * 24
    if unit == "w":
        return amount * 60 * 24 * 7
    return None


def _split_symbol_assets(symbol: str) -> tuple[str, str | None]:
    """Split common crypto pair notation into base and quote assets."""
    if "/" not in symbol:
        return symbol, None
    base, quote = symbol.split("/", 1)
    return base, quote


def _derive_market_context(
    rows: list[Any],
    *,
    entry_price: float,
    timeframe_minutes: int | None,
) -> dict[str, Any]:
    """Build provider-safe market context from recent OHLCV rows."""
    closes = [_safe_float(getattr(row, "close", None)) for row in rows]
    highs = [_safe_float(getattr(row, "high", None)) for row in rows]
    lows = [_safe_float(getattr(row, "low", None)) for row in rows]
    volumes = [_safe_float(getattr(row, "volume", None)) for row in rows]
    closes = [value for value in closes if value > 0]
    highs = [value for value in highs if value > 0]
    lows = [value for value in lows if value > 0]
    volumes = [value for value in volumes if value >= 0]

    latest_close = closes[-1] if closes else None
    latest_volume = volumes[-1] if volumes else None
    volume_window = volumes[-20:] if volumes else []
    avg_volume_20 = sum(volume_window) / len(volume_window) if volume_window else None

    returns: list[float] = []
    for previous, current in zip(closes[-21:-1], closes[-20:], strict=False):
        change = _pct_change(current, previous)
        if change is not None:
            returns.append(change)
    mean_return = sum(returns) / len(returns) if returns else 0.0
    variance = (
        sum((value - mean_return) ** 2 for value in returns) / len(returns)
        if returns
        else 0.0
    )

    recent_high = max(highs[-48:]) if highs else None
    recent_low = min(lows[-48:]) if lows else None
    recent_range = (
        recent_high - recent_low
        if recent_high is not None and recent_low is not None
        else None
    )
    range_position = (
        (entry_price - recent_low) / recent_range
        if recent_low is not None and recent_range and recent_range > 0
        else None
    )

    def close_n_back(count: int) -> float | None:
        if len(closes) <= count:
            return None
        return closes[-count - 1]

    return {
        "has_market_context": bool(closes),
        "candle_count": len(rows),
        "timeframe_minutes": timeframe_minutes,
        "latest_close": _round_or_none(latest_close, 12),
        "entry_vs_latest_close_pct": _round_or_none(
            _pct_change(entry_price, latest_close),
            4,
        ),
        "change_pct_3_candles": _round_or_none(
            _pct_change(latest_close or 0, close_n_back(3)),
            4,
        ),
        "change_pct_12_candles": _round_or_none(
            _pct_change(latest_close or 0, close_n_back(12)),
            4,
        ),
        "change_pct_48_candles": _round_or_none(
            _pct_change(latest_close or 0, close_n_back(48)),
            4,
        ),
        "realized_volatility_pct_20_candles": _round_or_none(
            math.sqrt(variance),
            4,
        ),
        "latest_volume_to_avg_20": _round_or_none(
            (
                latest_volume / avg_volume_20
                if latest_volume is not None and avg_volume_20
                else None
            ),
            4,
        ),
        "recent_high_low_position": _round_or_none(range_position, 4),
        "distance_from_recent_high_pct": _round_or_none(
            _pct_change(entry_price, recent_high),
            4,
        ),
        "distance_from_recent_low_pct": _round_or_none(
            _pct_change(entry_price, recent_low),
            4,
        ),
    }


async def enrich_entry_feature_bundle(
    feature_bundle: dict[str, Any],
) -> dict[str, Any]:
    """Add derived crypto-market context without exposing raw candles."""
    symbol = str(feature_bundle.get("symbol") or "")
    base_asset, quote_asset = _split_symbol_assets(symbol)
    enriched = {
        **feature_bundle,
        "domain_context": {
            "market": "crypto",
            "instrument_type": "spot_pair",
            "base_asset": base_asset,
            "quote_asset": quote_asset,
            "strategy_family": "dca_entry_observation",
        },
        "market_context": {
            "has_market_context": False,
            "candle_count": 0,
        },
    }
    try:
        rows = await model.Tickers.filter(symbol=symbol).order_by("-id").limit(96)
    except Exception as exc:  # noqa: BLE001 - missing context must not affect trading.
        logging.warning("AI trust market context unavailable for %s: %s", symbol, exc)
        return enriched

    rows = list(reversed(rows))
    entry_price = _safe_float(feature_bundle.get("position", {}).get("entry_price"))
    timeframe_minutes = feature_bundle.get("signal_context", {}).get(
        "timeframe_minutes"
    )
    enriched["market_context"] = _derive_market_context(
        rows,
        entry_price=entry_price,
        timeframe_minutes=(
            timeframe_minutes if isinstance(timeframe_minutes, int) else None
        ),
    )
    if entry_price <= 0:
        latest_close = _safe_float(enriched["market_context"].get("latest_close"))
        if latest_close > 0:
            enriched["position"] = {
                **dict(enriched.get("position") or {}),
                "entry_price": round(latest_close, 12),
                "entry_price_source": "latest_close",
            }
    return enriched


def _config_from_snapshot(snapshot: dict[str, Any]) -> AiTrustConfig:
    """Build an AI trust config from the full runtime config snapshot."""
    return AiTrustConfig(
        enabled=_safe_bool(snapshot.get("ai_trust_enabled", False)),
        enforce_warnings=_safe_bool(snapshot.get("ai_trust_enforce_warnings", False)),
        ollama_base_url=str(
            snapshot.get("ai_trust_ollama_base_url") or "http://localhost:11434"
        ).strip()
        or "http://localhost:11434",
        ollama_model=str(snapshot.get("ai_trust_ollama_model") or "").strip(),
        timeout_ms=max(250, _safe_int(snapshot.get("ai_trust_timeout_ms"), 10000)),
        max_retries=max(0, min(2, _safe_int(snapshot.get("ai_trust_max_retries"), 0))),
    )


async def get_ai_trust_config() -> AiTrustConfig:
    """Return the current AI trust service config."""
    config = await Config.instance()
    return _config_from_snapshot(config.snapshot())


async def is_entry_observation_enabled() -> bool:
    """Return whether entry observations should be scheduled."""
    try:
        return (await get_ai_trust_config()).enabled
    except Exception as exc:  # noqa: BLE001 - config failures must not affect trading.
        logging.error("AI trust config read failed: %s", exc, exc_info=True)
        return False


def build_entry_feature_bundle(
    symbol: str,
    payload: dict[str, Any],
    *,
    source_event: str = "open_deal",
) -> dict[str, Any]:
    """Build a provider-safe feature bundle from an entry payload."""
    price = _safe_float(payload.get("price") or payload.get("current_price"))
    amount = _safe_float(payload.get("amount") or payload.get("total_amount"))
    quote_size = _safe_float(payload.get("ordersize"))
    if amount <= 0 and price > 0 and quote_size > 0:
        amount = quote_size / price
    fee = _safe_float(payload.get("fee"))
    return {
        "schema_version": SCHEMA_VERSION,
        "source_event": source_event,
        "symbol": str(symbol or payload.get("symbol") or ""),
        "deal_id_present": bool(payload.get("deal_id")),
        "event_timestamp": str(payload.get("timestamp") or ""),
        "position": {
            "entry_price": round(price, 12),
            "entry_amount": round(amount, 12),
            "entry_notional": round(quote_size, 8),
            "fee": round(fee, 8),
        },
        "order_context": {
            "is_base_order": bool(payload.get("baseorder")),
            "is_safety_order": bool(payload.get("safetyorder")),
            "order_count": _safe_int(payload.get("order_count"), 0),
            "order_type": str(payload.get("ordertype") or ""),
            "side": str(payload.get("side") or ""),
            "direction": str(payload.get("direction") or ""),
        },
        "signal_context": {
            "has_signal_name": payload.get("signal_name") is not None,
            "has_strategy_name": payload.get("strategy_name") is not None,
            "timeframe_minutes": _timeframe_to_minutes(payload.get("timeframe")),
        },
    }


def validate_ai_trust_output(raw: Any) -> dict[str, Any]:
    """Validate structured model output before storing it as scored."""
    parsed = _parse_ai_trust_json(raw)

    prediction = _find_prediction_object(parsed)
    if prediction is None:
        raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)

    risk_score = _coerce_ai_int(prediction.get("risk_score"), minimum=0, maximum=100)
    confidence = _coerce_ai_float(
        prediction.get("confidence", 0.5),
        minimum=0,
        maximum=1,
    )
    warning_severity = _coerce_warning_severity(
        prediction.get("warning_severity"),
        risk_score=risk_score,
    )
    if "would_warn" in prediction:
        would_warn = _coerce_ai_bool(prediction.get("would_warn"))
    else:
        would_warn = warning_severity != "none" or risk_score >= 50
    would_warn, warning_severity = _normalize_warning_consistency(
        risk_score,
        would_warn,
        warning_severity,
    )
    normalized_reasons = _coerce_reason_codes(prediction.get("reason_codes"))

    operator_note = prediction.get("operator_note") or ""
    if isinstance(operator_note, list):
        operator_note = " ".join(str(part) for part in operator_note)
    elif isinstance(operator_note, dict):
        operator_note = (
            operator_note.get("note")
            or operator_note.get("text")
            or operator_note.get("explanation")
            or ""
        )

    return {
        "risk_score": risk_score,
        "confidence": round(confidence, 4),
        "would_warn": would_warn,
        "warning_severity": str(warning_severity),
        "reason_codes": normalized_reasons,
        "operator_note": str(operator_note).strip()[:240],
    }


async def _call_ollama(
    trust_config: AiTrustConfig,
    feature_bundle: dict[str, Any],
) -> dict[str, Any]:
    """Call Ollama and return locally validated structured output."""
    url = trust_config.ollama_base_url.rstrip("/") + "/api/chat"
    content = (
        "Score this Moonwalker entry observation for bad-entry risk. "
        "Return one compact JSON object matching the schema. Do not provide "
        "trading instructions, markdown, analysis, or extra text. Use "
        "operator_note only to explain the warning signal in one short sentence.\n\n"
        "Domain definitions:\n"
        "- Moonwalker is a crypto spot DCA trading bot.\n"
        "- A base order is the first buy that opens a deal.\n"
        "- A safety order is an additional DCA buy after price moves against "
        "an already-open deal.\n"
        "- A bad entry means an entry likely to close at non-positive profit, "
        "stay open unusually long, or need many safety orders.\n"
        "- Evaluate only shadow observation risk. Never recommend buy, sell, "
        "open, close, sizing, take-profit, or safety-order changes.\n"
        "- Prefer the derived market_context metrics over guessing.\n\n"
        f"Feature bundle:\n{json.dumps(feature_bundle, sort_keys=True)}"
    )
    request_payload = {
        "model": trust_config.ollama_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a shadow risk observer for a trading bot. "
                    "You understand crypto spot pairs and DCA terminology. "
                    "You never tell the operator to buy, sell, open, close, "
                    "size, or change orders. Keep risk_score, would_warn, "
                    "and warning_severity internally consistent."
                ),
            },
            {"role": "user", "content": content},
        ],
        "stream": False,
        "format": AI_TRUST_RESPONSE_SCHEMA,
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": OLLAMA_RESPONSE_NUM_PREDICT,
        },
    }
    timeout_seconds = trust_config.timeout_ms / 1000
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(url, json=request_payload)
        response.raise_for_status()
    body = response.json()
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, dict):
        raise AiTrustResponseError(PROVIDER_STATUS_SCHEMA_INVALID)
    content = message.get("content")
    logging.debug(
        "AI trust provider raw response content: %s",
        _truncate_provider_debug_text(content),
    )
    try:
        return validate_ai_trust_output(content)
    except AiTrustResponseError as exc:
        if str(exc) == PROVIDER_STATUS_SCHEMA_INVALID:
            logging.warning(
                "AI trust provider schema invalid: %s",
                _describe_ai_output_shape(content),
            )
        raise


async def _score_with_provider(
    trust_config: AiTrustConfig,
    feature_bundle: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Return provider status and scored output if available."""
    attempts = trust_config.max_retries + 1
    for attempt in range(attempts):
        try:
            scored = await _call_ollama(trust_config, feature_bundle)
            return PROVIDER_STATUS_SCORED, scored
        except httpx.TimeoutException:
            status = PROVIDER_STATUS_TIMEOUT
        except httpx.ConnectError:
            status = PROVIDER_STATUS_CONNECTION_ERROR
        except httpx.HTTPStatusError:
            status = PROVIDER_STATUS_PROVIDER_ERROR
        except json.JSONDecodeError:
            status = PROVIDER_STATUS_MALFORMED_JSON
        except AiTrustResponseError as exc:
            status = str(exc) or PROVIDER_STATUS_SCHEMA_INVALID
        except Exception as exc:  # noqa: BLE001 - provider failures are non-trading.
            logging.error("AI trust provider call failed: %s", exc, exc_info=True)
            status = PROVIDER_STATUS_UNEXPECTED_ERROR

        if attempt < attempts - 1:
            await asyncio.sleep(0)
    return status, None


async def _record_entry_prediction(
    *,
    symbol: str,
    payload: dict[str, Any],
    trust_config: AiTrustConfig,
    feature_bundle: dict[str, Any],
    provider_status: str,
    scored: dict[str, Any] | None,
    source_event: str,
    outcome_status: str = "open",
) -> None:
    """Persist one AI trust ledger row for an entry observation or gate."""
    status = "scored" if provider_status == PROVIDER_STATUS_SCORED else "unscored"
    await model.AiTrustPrediction.create(
        symbol=str(symbol or payload.get("symbol") or ""),
        deal_id=str(payload.get("deal_id")) if payload.get("deal_id") else None,
        trade_id=None,
        event_timestamp=str(payload.get("timestamp") or "") or None,
        source_event=source_event,
        provider=PROVIDER_NAME,
        model_name=trust_config.ollama_model or None,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        status=status,
        provider_status=provider_status,
        risk_score=scored.get("risk_score") if scored else None,
        confidence=scored.get("confidence") if scored else None,
        would_warn=scored.get("would_warn") if scored else None,
        warning_severity=scored.get("warning_severity") if scored else "none",
        reason_codes_json=_json_dumps(scored.get("reason_codes") if scored else []),
        operator_note=scored.get("operator_note") if scored else None,
        feature_bundle_json=_json_dumps(feature_bundle),
        outcome_status=outcome_status,
    )


async def observe_new_deal(symbol: str, payload: dict[str, Any]) -> None:
    """Record an optional shadow observation for a newly opened deal."""
    trust_config = await get_ai_trust_config()
    if not trust_config.enabled:
        return

    feature_bundle = await enrich_entry_feature_bundle(
        build_entry_feature_bundle(symbol, payload)
    )
    provider_status = PROVIDER_STATUS_MISSING_MODEL
    scored: dict[str, Any] | None = None
    if trust_config.ollama_model:
        provider_status, scored = await _score_with_provider(
            trust_config, feature_bundle
        )

    await _record_entry_prediction(
        symbol=str(symbol or payload.get("symbol") or ""),
        payload=payload,
        trust_config=trust_config,
        feature_bundle=feature_bundle,
        provider_status=provider_status,
        scored=scored,
        source_event="open_deal",
    )


async def _update_ai_trust_runtime_status(
    status: str,
    *,
    provider_status: str | None = None,
) -> None:
    """Persist the latest enforced AI gate status for dashboard status surfaces."""
    try:
        config = await Config.instance()
        await config.batch_set(
            {
                AI_TRUST_RUNTIME_STATUS_KEY: {"value": status, "type": "str"},
                AI_TRUST_RUNTIME_PROVIDER_STATUS_KEY: {
                    "value": provider_status or False,
                    "type": "str",
                },
                AI_TRUST_RUNTIME_UPDATED_AT_KEY: {
                    "value": (
                        datetime.now(UTC).isoformat()
                        if status != AI_TRUST_RUNTIME_STATUS_OK
                        else False
                    ),
                    "type": "str",
                },
            },
            notify_subscribers=False,
        )
    except Exception as exc:  # noqa: BLE001 - status writes must not permit entries.
        logging.warning(
            "AI trust runtime status update failed: %s",
            exc,
            exc_info=True,
        )


def _is_entry_enforcement_candidate(payload: dict[str, Any]) -> bool:
    """Return whether this buy intent can be blocked by AI entry enforcement."""
    return bool(payload.get("baseorder")) and not bool(payload.get("safetyorder"))


async def evaluate_entry_enforcement(
    symbol: str,
    payload: dict[str, Any],
    config_snapshot: dict[str, Any],
) -> AiTrustEntryGate:
    """Return whether optional AI warning enforcement allows an entry order."""
    trust_config = _config_from_snapshot(config_snapshot)
    if (
        not trust_config.enabled
        or not trust_config.enforce_warnings
        or not _is_entry_enforcement_candidate(payload)
    ):
        return AiTrustEntryGate(
            allowed=True,
            evaluated=False,
            provider_status=PROVIDER_STATUS_DISABLED,
        )

    gate_payload = {
        **payload,
        "symbol": str(symbol or payload.get("symbol") or ""),
        "timestamp": str(payload.get("timestamp") or "") or _now_ms_text(),
    }
    feature_bundle = await enrich_entry_feature_bundle(
        build_entry_feature_bundle(
            str(symbol or gate_payload.get("symbol") or ""),
            gate_payload,
            source_event="entry_preflight",
        )
    )
    provider_status = PROVIDER_STATUS_MISSING_MODEL
    scored: dict[str, Any] | None = None
    if trust_config.ollama_model:
        provider_status, scored = await _score_with_provider(
            trust_config,
            feature_bundle,
        )

    provider_unavailable = provider_status != PROVIDER_STATUS_SCORED
    warning_block = bool(
        provider_status == PROVIDER_STATUS_SCORED
        and scored is not None
        and scored.get("would_warn")
    )
    should_block = provider_unavailable or warning_block
    if should_block:
        try:
            await _record_entry_prediction(
                symbol=str(symbol or gate_payload.get("symbol") or ""),
                payload=gate_payload,
                trust_config=trust_config,
                feature_bundle=feature_bundle,
                provider_status=provider_status,
                scored=scored,
                source_event="entry_blocked",
                outcome_status="blocked",
            )
        except Exception as exc:  # noqa: BLE001 - ledger failures must not force buys.
            logging.error(
                "AI trust enforcement ledger write failed for %s: %s",
                symbol,
                exc,
                exc_info=True,
            )
        await _update_ai_trust_runtime_status(
            (
                AI_TRUST_RUNTIME_STATUS_PROVIDER_UNAVAILABLE
                if provider_unavailable
                else AI_TRUST_RUNTIME_STATUS_WARNING_BLOCKED
            ),
            provider_status=provider_status,
        )

    if not should_block:
        await _update_ai_trust_runtime_status(AI_TRUST_RUNTIME_STATUS_OK)
        return AiTrustEntryGate(
            allowed=True,
            evaluated=True,
            provider_status=provider_status,
            risk_score=scored.get("risk_score") if scored else None,
            warning_severity=scored.get("warning_severity") if scored else "none",
            operator_note=scored.get("operator_note") if scored else None,
        )

    return AiTrustEntryGate(
        allowed=False,
        evaluated=True,
        provider_status=provider_status,
        reason_code=(
            "ai_trust_unavailable" if provider_unavailable else "ai_trust_warning"
        ),
        risk_score=scored.get("risk_score") if scored else None,
        warning_severity=scored.get("warning_severity") if scored else "none",
        operator_note=scored.get("operator_note") if scored else None,
    )


def _bad_entry_label(closed_trade: Any) -> tuple[bool, list[str], float | None]:
    """Return bad-entry label, reasons, and parsed duration hours."""
    profit = _safe_float(getattr(closed_trade, "profit", None), 0.0)
    so_count = _safe_int(getattr(closed_trade, "so_count", None), 0)
    duration_hours = helper.parse_duration_hours(
        getattr(closed_trade, "duration", None),
        open_date=getattr(closed_trade, "open_date", None),
        close_date=getattr(closed_trade, "close_date", None),
    )
    reasons: list[str] = []
    if profit <= 0:
        reasons.append("non_positive_profit")
    if duration_hours is not None and duration_hours >= BAD_ENTRY_SLOW_HOURS:
        reasons.append("slow_close")
    if so_count >= BAD_ENTRY_HEAVY_SAFETY_ORDERS:
        reasons.append("safety_order_heavy")
    return bool(reasons), reasons, duration_hours


async def attribute_closed_outcome(deal_id: str | None) -> None:
    """Attach closed-trade outcome information to matching predictions."""
    normalized_deal_id = str(deal_id or "").strip()
    if not normalized_deal_id:
        return
    closed_trade = await model.ClosedTrades.filter(deal_id=normalized_deal_id).first()
    if closed_trade is None:
        return
    bad_entry, reasons, duration_hours = _bad_entry_label(closed_trade)
    await model.AiTrustPrediction.filter(deal_id=normalized_deal_id).update(
        outcome_status="closed",
        bad_entry=bad_entry,
        bad_entry_reasons_json=_json_dumps(reasons),
        outcome_profit=closed_trade.profit,
        outcome_profit_percent=closed_trade.profit_percent,
        outcome_duration_hours=(
            round(duration_hours, 4) if duration_hours is not None else None
        ),
        outcome_so_count=closed_trade.so_count,
    )


async def has_prediction_for_deal(deal_id: str | None) -> bool:
    """Return whether a deal has AI trust rows to calibrate."""
    normalized_deal_id = str(deal_id or "").strip()
    if not normalized_deal_id:
        return False
    try:
        return await model.AiTrustPrediction.filter(deal_id=normalized_deal_id).exists()
    except Exception as exc:  # noqa: BLE001 - calibration must stay non-trading.
        logging.error(
            "AI trust prediction lookup failed for %s: %s",
            normalized_deal_id,
            exc,
            exc_info=True,
        )
        return False


def _parse_json_list(value: str | None) -> list[str]:
    """Parse a JSON list of strings from the ledger."""
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if isinstance(item, str)]


def _prediction_to_api(row: model.AiTrustPrediction) -> dict[str, Any]:
    """Return a compact API representation of a prediction row."""
    return {
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


async def build_analytics_payload() -> dict[str, Any]:
    """Return the reduced Statistics payload for AI trust calibration."""
    trust_config = await get_ai_trust_config()
    rows = await model.AiTrustPrediction.all().order_by("-created_at")
    total = len(rows)
    scored_rows = [row for row in rows if row.status == "scored"]
    unscored_rows = [row for row in rows if row.status != "scored"]
    closed_rows = [row for row in rows if row.outcome_status == "closed"]
    warning_rows = [row for row in scored_rows if bool(row.would_warn)]
    false_warnings = [
        row
        for row in warning_rows
        if row.outcome_status == "closed" and not row.bad_entry
    ]
    bad_entries = [row for row in closed_rows if bool(row.bad_entry)]
    captured_bad_entries = [row for row in bad_entries if bool(row.would_warn)]
    provider_counts: dict[str, int] = {}
    for row in rows:
        provider_counts[row.provider_status] = (
            provider_counts.get(row.provider_status, 0) + 1
        )

    def _rate(numerator: int, denominator: int) -> float:
        return round((numerator / denominator) * 100, 2) if denominator else 0.0

    recent = rows[:MAX_RECENT_PREDICTIONS]
    review = [
        row
        for row in rows
        if row.outcome_status == "closed" and (row.bad_entry or row.would_warn)
    ][:MAX_BAD_ENTRY_REVIEW]
    return {
        "enabled": trust_config.enabled,
        "enforce_warnings": trust_config.enforce_warnings,
        "configured": bool(trust_config.ollama_model),
        "provider": PROVIDER_NAME,
        "model_name": trust_config.ollama_model or None,
        "status": (
            "disabled"
            if not trust_config.enabled
            else "missing_model" if not trust_config.ollama_model else "ready"
        ),
        "coverage": {
            "total": total,
            "scored": len(scored_rows),
            "unscored": len(unscored_rows),
            "closed": len(closed_rows),
            "coverage_rate": _rate(len(scored_rows), total),
        },
        "quality": {
            "warning_hit_rate": _rate(
                len([row for row in warning_rows if row.bad_entry]),
                len(warning_rows),
            ),
            "false_warning_rate": _rate(len(false_warnings), len(warning_rows)),
            "bad_entry_capture_rate": _rate(
                len(captured_bad_entries),
                len(bad_entries),
            ),
            "bad_entries": len(bad_entries),
            "warnings": len(warning_rows),
        },
        "provider_status_counts": provider_counts,
        "recent_predictions": [_prediction_to_api(row) for row in recent],
        "bad_entry_review": [_prediction_to_api(row) for row in review],
    }


def schedule_entry_observation(symbol: str, payload: dict[str, Any]) -> None:
    """Schedule entry observation without coupling it to trade persistence."""

    async def _run() -> None:
        try:
            await observe_new_deal(symbol, dict(payload))
        except Exception as exc:  # noqa: BLE001 - shadow observer must never leak.
            logging.error(
                "AI trust entry observation failed for %s: %s",
                symbol,
                exc,
                exc_info=True,
            )

    asyncio.create_task(_run())


def schedule_outcome_attribution(deal_id: str | None) -> None:
    """Schedule closed-outcome attribution without blocking trade closure."""

    async def _run() -> None:
        try:
            await attribute_closed_outcome(deal_id)
        except Exception as exc:  # noqa: BLE001 - calibration must never leak.
            logging.error(
                "AI trust outcome attribution failed for %s: %s",
                deal_id,
                exc,
                exc_info=True,
            )

    asyncio.create_task(_run())
