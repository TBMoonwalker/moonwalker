"""Persisted symbol-memory service for adaptive Autopilot behavior."""

from __future__ import annotations

import asyncio
import copy
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import helper
import model
from service.config import Config
from service.database import run_sqlite_write_with_retry
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger(
    "logs/autopilot_memory.log",
    "autopilot_memory",
)

_DURATION_PATTERN = re.compile(
    r"^(?:(?P<days>\d+)\s+days?,\s*)?"
    r"(?P<hours>\d{1,2}):(?P<minutes>\d{2}):(?P<seconds>\d{2})"
    r"(?:\.(?P<microseconds>\d+))?$"
)


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    """Best-effort parsing for the mixed date formats used in closed trades."""
    if isinstance(value, datetime):
        return _ensure_utc(value)

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1_000_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None

    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None

    if normalized.isdigit():
        return _parse_datetime(int(normalized))

    for candidate in (
        normalized.replace("Z", "+00:00"),
        normalized,
    ):
        try:
            return _ensure_utc(datetime.fromisoformat(candidate))
        except ValueError:
            continue

    for pattern in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return _ensure_utc(datetime.strptime(normalized, pattern))
        except ValueError:
            continue

    return None


def _parse_duration_hours(
    value: Any,
    *,
    open_date: Any,
    close_date: Any,
) -> float | None:
    """Return duration in hours using the best available source."""
    opened_at = _parse_datetime(open_date)
    closed_at = _parse_datetime(close_date)
    if opened_at and closed_at and closed_at >= opened_at:
        return max((closed_at - opened_at).total_seconds() / 3600, 0.0)

    if value is None:
        return None

    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric >= 3600:
            return numeric / 3600
        if numeric >= 60:
            return numeric / 60
        return numeric

    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None

    try:
        return _parse_duration_hours(float(normalized), open_date=None, close_date=None)
    except ValueError:
        pass

    matched = _DURATION_PATTERN.match(normalized)
    if matched:
        days = int(matched.group("days") or 0)
        hours = int(matched.group("hours") or 0)
        minutes = int(matched.group("minutes") or 0)
        seconds = int(matched.group("seconds") or 0)
        microseconds = int((matched.group("microseconds") or "0")[:6].ljust(6, "0"))
        total_seconds = (
            days * 86_400
            + hours * 3_600
            + minutes * 60
            + seconds
            + microseconds / 1_000_000
        )
        return total_seconds / 3600

    return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a numeric value into the provided bounds."""
    return max(minimum, min(maximum, value))


def _safe_float(value: Any) -> float:
    """Convert the given value into a finite float or fall back to 0.0."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return parsed


def _safe_int(value: Any, default: int = 0) -> int:
    """Convert the given value into an int or fall back to the provided default."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _isoformat_or_none(value: datetime | None) -> str | None:
    """Return a stable ISO timestamp string for API responses."""
    if value is None:
        return None
    return _ensure_utc(value).isoformat().replace("+00:00", "Z")


def _round_float(value: float | None, digits: int = 4) -> float | None:
    """Round floats for API payload readability."""
    if value is None:
        return None
    return round(float(value), digits)


def _normalize_symbol_key(value: Any) -> str:
    """Return a stable uppercase symbol key for cache lookups."""
    return str(value or "").strip().upper()


def _confidence_bucket(sample_size: int) -> str:
    """Map sample size to the cockpit confidence language."""
    if sample_size >= 8:
        return "confident"
    if sample_size >= 4:
        return "usable"
    return "warming_up"


def _tp_delta_limit(baseline_take_profit: float) -> float:
    """Return the maximum absolute TP delta for adaptive adjustments."""
    return _clamp(abs(baseline_take_profit) * 0.15, 0.15, 0.5)


def _base_order_delta_limit(
    base_order_amount: float,
    *,
    stretch_multiplier: float = 1.0,
) -> float:
    """Return the maximum read-only base-order suggestion delta."""
    if base_order_amount <= 0:
        return 0.0
    return max(base_order_amount * 0.15, 5.0) * max(1.0, stretch_multiplier)


def _base_order_stretch_multiplier(config: dict[str, Any]) -> float:
    """Return configured Autopilot base-order stretch multiplier."""
    if not bool(config.get("autopilot_profit_stretch_enabled", False)):
        return 1.0
    configured_multiplier = config.get(
        "autopilot_base_order_stretch_max_multiplier",
        config.get("autopilot_entry_stretch_max_multiplier"),
    )
    return max(
        1.0,
        _safe_float(configured_multiplier) or 1.0,
    )


def _memory_status_reason_code(state: dict[str, Any]) -> str | None:
    """Return a stable reason code for non-fresh memory states."""
    status = str(state.get("status") or "")
    if status == "stale":
        return str(state.get("stale_reason") or "snapshot_expired")
    if status == "warming_up":
        return "memory_warming_up"
    if status == "empty":
        return "memory_empty"
    if status:
        return f"memory_{status}"
    return None


@dataclass(frozen=True)
class ClosedTradeMemoryRow:
    """Normalized closed-trade information used by the trust engine."""

    symbol: str
    close_date: datetime
    duration_hours: float | None
    profit: float
    profit_percent: float


@dataclass(frozen=True)
class SymbolMemorySnapshot:
    """Latest trust snapshot for one symbol."""

    symbol: str
    trust_score: float
    trust_direction: str
    confidence_bucket: str
    confidence_progress: float
    sample_size: int
    profitable_closes: int
    loss_count: int
    slow_close_count: int
    weighted_profit_percent: float
    weighted_close_hours: float
    tp_delta_ratio: float
    suggested_base_order: float
    primary_reason_code: str | None
    primary_reason_value: int | None
    secondary_reason_code: str | None
    secondary_reason_value: int | None
    last_closed_at: datetime | None

    def to_model_payload(self) -> dict[str, Any]:
        """Convert the snapshot into a Tortoise model payload."""
        payload = asdict(self)
        payload["last_closed_at"] = self.last_closed_at
        return payload

    def to_api_payload(self) -> dict[str, Any]:
        """Convert the snapshot into a JSON-serializable API payload."""
        return {
            "symbol": self.symbol,
            "trust_score": _round_float(self.trust_score, 2),
            "trust_direction": self.trust_direction,
            "confidence_bucket": self.confidence_bucket,
            "confidence_progress": _round_float(self.confidence_progress, 2),
            "sample_size": self.sample_size,
            "profitable_closes": self.profitable_closes,
            "loss_count": self.loss_count,
            "slow_close_count": self.slow_close_count,
            "weighted_profit_percent": _round_float(
                self.weighted_profit_percent,
                3,
            ),
            "weighted_close_hours": _round_float(self.weighted_close_hours, 3),
            "tp_delta_ratio": _round_float(self.tp_delta_ratio, 3),
            "suggested_base_order": _round_float(self.suggested_base_order, 2),
            "primary_reason_code": self.primary_reason_code,
            "primary_reason_value": self.primary_reason_value,
            "secondary_reason_code": self.secondary_reason_code,
            "secondary_reason_value": self.secondary_reason_value,
            "last_closed_at": _isoformat_or_none(self.last_closed_at),
        }


@dataclass(frozen=True)
class SymbolAdmissionProfile:
    """Admission-facing trust view for one symbol."""

    symbol: str
    memory_status: str
    trust_direction: str
    trust_score: float | None
    reason_code: str | None
    uses_trust_ranking: bool


@dataclass(frozen=True)
class MemoryEventCandidate:
    """One event that should be persisted into the recent event log."""

    event_type: str
    tone: str
    symbol: str | None = None
    reason_code: str | None = None
    reason_value: int | None = None
    trust_score: float | None = None

    def to_model_payload(self) -> dict[str, Any]:
        """Convert the candidate into a model payload."""
        return {
            "event_type": self.event_type,
            "tone": self.tone,
            "symbol": self.symbol,
            "reason_code": self.reason_code,
            "reason_value": self.reason_value,
            "trust_score": self.trust_score,
        }


class AutopilotMemoryService:
    """Refresh, persist, and expose symbol-memory trust data."""

    _instance: AutopilotMemoryService | None = None
    _lock = asyncio.Lock()

    STATE_ROW_ID = 1
    MAX_ANALYSIS_ROWS = 5_000
    MAX_TRUST_ROWS = 5
    MAX_EVENT_ROWS = 40
    REFRESH_INTERVAL_SECONDS = 60.0
    IDLE_LOOP_SECONDS = 15.0
    STALE_AFTER_SECONDS = REFRESH_INTERVAL_SECONDS * 3
    REQUIRED_CLOSES = 20
    MIN_SYMBOL_CLOSES = 3
    SYMBOL_CONFIDENT_CLOSES = 8
    DECAY_DAYS = 21.0

    def __init__(self) -> None:
        """Initialize collaborators and process-local caches."""
        self.config: dict[str, Any] = {}
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._state = self._build_default_state()
        self._snapshots: list[SymbolMemorySnapshot] = []
        self._snapshot_map: dict[str, SymbolMemorySnapshot] = {}
        self._events: list[dict[str, Any]] = []

    @classmethod
    async def instance(cls) -> "AutopilotMemoryService":
        """Return the shared symbol-memory service instance."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                await cls._instance.init()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Clear the singleton for isolated tests."""
        cls._instance = None

    @classmethod
    def _build_default_state(cls) -> dict[str, Any]:
        """Return the default service state."""
        return {
            "status": "empty",
            "enabled": False,
            "stale_reason": None,
            "baseline_mode_active": True,
            "current_closes": 0,
            "required_closes": cls.REQUIRED_CLOSES,
            "symbols_considered": 0,
            "trusted_symbols": 0,
            "cooling_symbols": 0,
            "featured_symbol": None,
            "featured_direction": None,
            "featured_reason_code": None,
            "featured_reason_value": None,
            "adaptive_tp_min": None,
            "adaptive_tp_max": None,
            "suggested_base_order_min": None,
            "suggested_base_order_max": None,
            "last_updated_at": None,
            "last_success_at": None,
        }

    async def init(self) -> None:
        """Subscribe to config changes and warm the persisted cache."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config.snapshot())
        await self._load_persisted_state()
        await self.refresh_state()

    async def start(self) -> None:
        """Start the periodic refresh loop."""
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def shutdown(self) -> None:
        """Stop the periodic refresh loop."""
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Capture the latest config snapshot for future refreshes."""
        self.config = config

    def get_state(self) -> dict[str, Any]:
        """Return a defensive copy of the latest global service state."""
        return copy.deepcopy(self._state_with_staleness())

    def get_runtime_summary(self) -> dict[str, Any]:
        """Return the compact summary used by autopilot runtime/state payloads."""
        state = self._state_with_staleness()
        return {
            "status": state["status"],
            "enabled": state["enabled"],
            "stale": state["status"] == "stale",
            "stale_reason": state["stale_reason"],
            "current_closes": state["current_closes"],
            "required_closes": state["required_closes"],
            "featured_symbol": state["featured_symbol"],
            "featured_direction": state["featured_direction"],
            "last_updated_at": _isoformat_or_none(state["last_updated_at"]),
            "last_success_at": _isoformat_or_none(state["last_success_at"]),
        }

    def resolve_symbol_policy(
        self,
        symbol: str,
        *,
        enabled: bool,
        baseline_take_profit: float,
        base_order_amount: float,
        entry_sizing_enabled: bool = False,
    ) -> dict[str, Any]:
        """Resolve adaptive TP/suggested sizing for one symbol from the cache."""
        state = self._state_with_staleness()
        snapshot = self._snapshot_map.get(_normalize_symbol_key(symbol))
        take_profit = float(baseline_take_profit)
        baseline_base_order = round(base_order_amount, 8)
        memory_status = str(state["status"])
        trust_score = snapshot.trust_score if snapshot else None
        trust_direction = snapshot.trust_direction if snapshot else "neutral"

        if not enabled:
            return {
                "apply_tp": False,
                "take_profit": take_profit,
                "suggested_base_order": baseline_base_order,
                "apply_entry_size": False,
                "entry_order_size": baseline_base_order,
                "entry_reason_code": "autopilot_disabled",
                "memory_status": memory_status,
                "reason_code": "autopilot_disabled",
                "trust_score": trust_score,
                "trust_direction": trust_direction,
            }

        if (
            state["status"] != "fresh"
            or snapshot is None
            or snapshot.trust_direction == "neutral"
        ):
            return {
                "apply_tp": False,
                "take_profit": take_profit,
                "suggested_base_order": baseline_base_order,
                "apply_entry_size": False,
                "entry_order_size": baseline_base_order,
                "entry_reason_code": (
                    _memory_status_reason_code(state)
                    if state["status"] != "fresh"
                    else "snapshot_missing" if snapshot is None else "neutral_trust"
                ),
                "memory_status": memory_status,
                "reason_code": (
                    _memory_status_reason_code(state)
                    if state["status"] != "fresh"
                    else "snapshot_missing" if snapshot is None else "neutral_trust"
                ),
                "trust_score": trust_score,
                "trust_direction": trust_direction,
            }

        delta_limit = _tp_delta_limit(take_profit)
        adjusted_tp = max(0.0, take_profit + snapshot.tp_delta_ratio * delta_limit)
        suggested_base_order = snapshot.suggested_base_order or round(
            base_order_amount,
            8,
        )
        entry_reason_code = snapshot.primary_reason_code
        apply_entry_size = bool(entry_sizing_enabled)
        entry_order_size = round(float(suggested_base_order), 8)
        if not entry_sizing_enabled:
            apply_entry_size = False
            entry_order_size = baseline_base_order
            entry_reason_code = "entry_sizing_disabled"
        elif entry_order_size <= 0:
            apply_entry_size = False
            entry_order_size = baseline_base_order
            entry_reason_code = "invalid_suggested_base_order"
        return {
            "apply_tp": True,
            "take_profit": round(adjusted_tp, 8),
            "suggested_base_order": round(float(suggested_base_order), 8),
            "apply_entry_size": apply_entry_size,
            "entry_order_size": entry_order_size,
            "entry_reason_code": entry_reason_code,
            "memory_status": memory_status,
            "reason_code": snapshot.primary_reason_code,
            "trust_score": snapshot.trust_score,
            "trust_direction": snapshot.trust_direction,
        }

    def build_admission_profiles(
        self,
        symbols: list[str],
        *,
        enabled: bool,
    ) -> dict[str, SymbolAdmissionProfile]:
        """Return admission-ready trust metadata keyed by normalized symbol."""
        state = self._state_with_staleness()
        profiles: dict[str, SymbolAdmissionProfile] = {}
        for symbol in symbols:
            normalized_symbol = _normalize_symbol_key(symbol)
            if not normalized_symbol:
                continue
            snapshot = self._snapshot_map.get(normalized_symbol)

            if not enabled:
                profiles[normalized_symbol] = SymbolAdmissionProfile(
                    symbol=normalized_symbol,
                    memory_status="disabled",
                    trust_direction="neutral",
                    trust_score=snapshot.trust_score if snapshot else None,
                    reason_code="autopilot_disabled",
                    uses_trust_ranking=False,
                )
                continue

            if state["status"] != "fresh":
                profiles[normalized_symbol] = SymbolAdmissionProfile(
                    symbol=normalized_symbol,
                    memory_status=str(state["status"]),
                    trust_direction="neutral",
                    trust_score=snapshot.trust_score if snapshot else None,
                    reason_code=state.get("stale_reason"),
                    uses_trust_ranking=False,
                )
                continue

            if snapshot is None:
                profiles[normalized_symbol] = SymbolAdmissionProfile(
                    symbol=normalized_symbol,
                    memory_status="fresh",
                    trust_direction="neutral",
                    trust_score=None,
                    reason_code="snapshot_missing",
                    uses_trust_ranking=False,
                )
                continue

            profiles[normalized_symbol] = SymbolAdmissionProfile(
                symbol=normalized_symbol,
                memory_status="fresh",
                trust_direction=snapshot.trust_direction,
                trust_score=snapshot.trust_score,
                reason_code=snapshot.primary_reason_code,
                uses_trust_ranking=True,
            )

        return profiles

    def build_read_model(self) -> dict[str, Any]:
        """Return the cockpit read model for the latest persisted snapshot."""
        state = self._state_with_staleness()
        entry_sizing_configured = bool(
            self.config.get("autopilot_symbol_entry_sizing_enabled", False)
        )
        entry_sizing_active = bool(state["enabled"]) and (
            state["status"] == "fresh" and entry_sizing_configured
        )
        entry_sizing_reason_code = None
        if not entry_sizing_configured:
            entry_sizing_reason_code = "entry_sizing_disabled"
        elif state["status"] != "fresh":
            entry_sizing_reason_code = _memory_status_reason_code(state)
        elif not state["enabled"]:
            entry_sizing_reason_code = "autopilot_disabled"
        favored = [
            snapshot.to_api_payload()
            for snapshot in sorted(
                self._snapshots,
                key=lambda snapshot: (-snapshot.trust_score, snapshot.symbol),
            )
            if snapshot.trust_direction == "favored"
        ][: self.MAX_TRUST_ROWS]
        cooling = [
            snapshot.to_api_payload()
            for snapshot in sorted(
                self._snapshots,
                key=lambda snapshot: (snapshot.trust_score, snapshot.symbol),
            )
            if snapshot.trust_direction == "cooling"
        ][: self.MAX_TRUST_ROWS]
        featured = None
        if state["featured_symbol"]:
            featured_snapshot = self._snapshot_map.get(
                _normalize_symbol_key(state["featured_symbol"])
            )
            if featured_snapshot is not None:
                featured = featured_snapshot.to_api_payload()

        return {
            "status": state["status"],
            "enabled": bool(state["enabled"]),
            "stale": state["status"] == "stale",
            "stale_reason": state["stale_reason"],
            "baseline_mode_active": bool(state["baseline_mode_active"]),
            "updated_at": _isoformat_or_none(state["last_updated_at"]),
            "last_success_at": _isoformat_or_none(state["last_success_at"]),
            "warmup": {
                "current_closes": int(state["current_closes"]),
                "required_closes": int(state["required_closes"]),
                "progress_percent": _round_float(
                    (
                        min(
                            float(state["current_closes"])
                            / max(float(state["required_closes"]), 1.0),
                            1.0,
                        )
                        * 100
                    ),
                    1,
                ),
            },
            "featured": featured,
            "entry_sizing": {
                "configured": entry_sizing_configured,
                "active": entry_sizing_active,
                "reason_code": entry_sizing_reason_code,
            },
            "portfolio_effect": {
                "adaptive_tp_min": _round_float(state["adaptive_tp_min"], 4),
                "adaptive_tp_max": _round_float(state["adaptive_tp_max"], 4),
                "suggested_base_order_min": _round_float(
                    state["suggested_base_order_min"],
                    2,
                ),
                "suggested_base_order_max": _round_float(
                    state["suggested_base_order_max"],
                    2,
                ),
            },
            "trust_board": {
                "favored": favored,
                "cooling": cooling,
            },
            "events": copy.deepcopy(self._events),
        }

    async def refresh_state(self) -> None:
        """Recompute the persisted symbol-memory state from closed trades."""
        try:
            raw_rows = (
                await model.ClosedTrades.all()
                .order_by("-id")
                .limit(self.MAX_ANALYSIS_ROWS)
                .values(
                    "symbol",
                    "close_date",
                    "duration",
                    "open_date",
                    "profit",
                    "profit_percent",
                )
            )
            computation = self._compute_state(raw_rows)
            events = self._build_refresh_events(
                previous_state=self._state_with_staleness(),
                previous_snapshots=self._snapshot_map,
                next_state=computation["state"],
                next_snapshots=computation["snapshots"],
            )
            await self._persist_snapshot(
                state_payload=computation["state"],
                snapshots=computation["snapshots"],
                events=events,
            )
            self._state = computation["state"]
            self._snapshots = computation["snapshots"]
            self._snapshot_map = {
                _normalize_symbol_key(snapshot.symbol): snapshot
                for snapshot in self._snapshots
            }
            await self._load_events()
        except Exception as exc:  # noqa: BLE001 - keep service resilient.
            logging.error("Autopilot memory refresh failed: %s", exc, exc_info=True)
            await self._mark_stale("refresh_failed")

    async def _run_loop(self) -> None:
        """Refresh the memory snapshot on a fixed interval."""
        while self._running:
            try:
                await self.refresh_state()
            except Exception as exc:  # noqa: BLE001 - defensive outer loop.
                logging.error(
                    "Autopilot memory loop failed: %s",
                    exc,
                    exc_info=True,
                )

            interval = (
                self.REFRESH_INTERVAL_SECONDS
                if bool(self.config.get("autopilot", False))
                else self.IDLE_LOOP_SECONDS
            )
            await asyncio.sleep(interval)

    async def _load_persisted_state(self) -> None:
        """Warm the in-memory cache from persisted snapshot tables."""
        persisted_state = await model.AutopilotMemoryState.filter(
            id=self.STATE_ROW_ID
        ).first()
        if persisted_state is not None:
            self._state = {
                "status": persisted_state.status,
                "enabled": persisted_state.enabled,
                "stale_reason": persisted_state.stale_reason,
                "baseline_mode_active": persisted_state.baseline_mode_active,
                "current_closes": persisted_state.current_closes,
                "required_closes": persisted_state.required_closes,
                "symbols_considered": persisted_state.symbols_considered,
                "trusted_symbols": persisted_state.trusted_symbols,
                "cooling_symbols": persisted_state.cooling_symbols,
                "featured_symbol": persisted_state.featured_symbol,
                "featured_direction": persisted_state.featured_direction,
                "featured_reason_code": persisted_state.featured_reason_code,
                "featured_reason_value": persisted_state.featured_reason_value,
                "adaptive_tp_min": persisted_state.adaptive_tp_min,
                "adaptive_tp_max": persisted_state.adaptive_tp_max,
                "suggested_base_order_min": persisted_state.suggested_base_order_min,
                "suggested_base_order_max": persisted_state.suggested_base_order_max,
                "last_updated_at": persisted_state.last_updated_at,
                "last_success_at": persisted_state.last_success_at,
            }

        rows = await model.AutopilotSymbolMemory.all().order_by(
            "-trust_score", "symbol"
        )
        self._snapshots = [
            SymbolMemorySnapshot(
                symbol=row.symbol,
                trust_score=float(row.trust_score or 0.0),
                trust_direction=row.trust_direction,
                confidence_bucket=row.confidence_bucket,
                confidence_progress=float(row.confidence_progress or 0.0),
                sample_size=int(row.sample_size or 0),
                profitable_closes=int(row.profitable_closes or 0),
                loss_count=int(row.loss_count or 0),
                slow_close_count=int(row.slow_close_count or 0),
                weighted_profit_percent=float(row.weighted_profit_percent or 0.0),
                weighted_close_hours=float(row.weighted_close_hours or 0.0),
                tp_delta_ratio=float(row.tp_delta_ratio or 0.0),
                suggested_base_order=float(row.suggested_base_order or 0.0),
                primary_reason_code=row.primary_reason_code,
                primary_reason_value=row.primary_reason_value,
                secondary_reason_code=row.secondary_reason_code,
                secondary_reason_value=row.secondary_reason_value,
                last_closed_at=row.last_closed_at,
            )
            for row in rows
        ]
        self._snapshots.sort(
            key=lambda snapshot: (
                snapshot.trust_direction != "favored",
                -snapshot.trust_score,
                snapshot.symbol,
            )
        )
        self._snapshot_map = {
            _normalize_symbol_key(snapshot.symbol): snapshot
            for snapshot in self._snapshots
        }
        await self._load_events()

    async def _load_events(self) -> None:
        """Warm the in-memory event log from persisted rows."""
        rows = (
            await model.AutopilotMemoryEvent.all()
            .order_by("-created_at", "-id")
            .limit(self.MAX_EVENT_ROWS)
        )
        self._events = [
            {
                "event_type": row.event_type,
                "tone": row.tone,
                "symbol": row.symbol,
                "reason_code": row.reason_code,
                "reason_value": row.reason_value,
                "trust_score": _round_float(row.trust_score, 2),
                "created_at": _isoformat_or_none(row.created_at),
            }
            for row in rows
        ]

    async def _persist_snapshot(
        self,
        *,
        state_payload: dict[str, Any],
        snapshots: list[SymbolMemorySnapshot],
        events: list[MemoryEventCandidate],
    ) -> None:
        """Persist a successful refresh atomically."""

        async def _operation() -> None:
            async with in_transaction() as conn:
                await model.AutopilotMemoryState.filter(id=self.STATE_ROW_ID).using_db(
                    conn
                ).delete()
                await model.AutopilotMemoryState.create(
                    id=self.STATE_ROW_ID,
                    using_db=conn,
                    **state_payload,
                )
                await model.AutopilotSymbolMemory.all().using_db(conn).delete()
                if snapshots:
                    await model.AutopilotSymbolMemory.bulk_create(
                        [
                            model.AutopilotSymbolMemory(**snapshot.to_model_payload())
                            for snapshot in snapshots
                        ],
                        using_db=conn,
                    )
                if events:
                    await model.AutopilotMemoryEvent.bulk_create(
                        [
                            model.AutopilotMemoryEvent(**event.to_model_payload())
                            for event in events
                        ],
                        using_db=conn,
                    )
                extra_event_ids = (
                    await model.AutopilotMemoryEvent.all()
                    .using_db(conn)
                    .order_by("-created_at", "-id")
                    .offset(self.MAX_EVENT_ROWS)
                    .values_list("id", flat=True)
                )
                if extra_event_ids:
                    await model.AutopilotMemoryEvent.filter(
                        id__in=list(extra_event_ids)
                    ).using_db(conn).delete()

        await run_sqlite_write_with_retry(
            _operation,
            "persisting autopilot memory snapshot",
        )

    async def _mark_stale(self, reason_code: str) -> None:
        """Persist a stale-state marker without deleting the last good snapshot."""
        state = self._state_with_staleness()
        now = _utc_now()
        stale_state = {
            **state,
            "status": "stale",
            "stale_reason": reason_code,
            "baseline_mode_active": True,
            "last_updated_at": now,
            "enabled": bool(self.config.get("autopilot", False)),
        }
        event = []
        if state.get("status") != "stale" or state.get("stale_reason") != reason_code:
            event.append(
                MemoryEventCandidate(
                    event_type="memory_stale",
                    tone="warning",
                    reason_code=reason_code,
                )
            )

        async def _operation() -> None:
            async with in_transaction() as conn:
                await model.AutopilotMemoryState.filter(id=self.STATE_ROW_ID).using_db(
                    conn
                ).delete()
                await model.AutopilotMemoryState.create(
                    id=self.STATE_ROW_ID,
                    using_db=conn,
                    **stale_state,
                )
                if event:
                    await model.AutopilotMemoryEvent.bulk_create(
                        [
                            model.AutopilotMemoryEvent(**candidate.to_model_payload())
                            for candidate in event
                        ],
                        using_db=conn,
                    )
                extra_event_ids = (
                    await model.AutopilotMemoryEvent.all()
                    .using_db(conn)
                    .order_by("-created_at", "-id")
                    .offset(self.MAX_EVENT_ROWS)
                    .values_list("id", flat=True)
                )
                if extra_event_ids:
                    await model.AutopilotMemoryEvent.filter(
                        id__in=list(extra_event_ids)
                    ).using_db(conn).delete()

        await run_sqlite_write_with_retry(
            _operation,
            "persisting autopilot memory stale marker",
        )
        self._state = stale_state
        await self._load_events()

    def _state_with_staleness(self) -> dict[str, Any]:
        """Return current state with dynamic staleness evaluation applied."""
        state = copy.deepcopy(self._state)
        last_success_at = state.get("last_success_at")
        if isinstance(last_success_at, datetime):
            age_seconds = (_utc_now() - _ensure_utc(last_success_at)).total_seconds()
            if age_seconds > self.STALE_AFTER_SECONDS and state.get("status") not in {
                "empty",
                "warming_up",
            }:
                state["status"] = "stale"
                state["stale_reason"] = state.get("stale_reason") or "snapshot_expired"
                state["baseline_mode_active"] = True
        return state

    def _compute_state(self, raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the next global state and symbol snapshots from closed trades."""
        now = _utc_now()
        closed_rows: list[ClosedTradeMemoryRow] = []
        profitable_durations: list[float] = []

        for raw_row in raw_rows:
            symbol = str(raw_row.get("symbol") or "").strip()
            close_date = _parse_datetime(raw_row.get("close_date"))
            if not symbol or close_date is None:
                continue
            duration_hours = _parse_duration_hours(
                raw_row.get("duration"),
                open_date=raw_row.get("open_date"),
                close_date=raw_row.get("close_date"),
            )
            profit = _safe_float(raw_row.get("profit"))
            profit_percent = _safe_float(raw_row.get("profit_percent"))
            closed_rows.append(
                ClosedTradeMemoryRow(
                    symbol=symbol,
                    close_date=close_date,
                    duration_hours=duration_hours,
                    profit=profit,
                    profit_percent=profit_percent,
                )
            )
            if duration_hours is not None and profit >= 0:
                profitable_durations.append(duration_hours)

        required_closes = self.REQUIRED_CLOSES
        enabled = bool(self.config.get("autopilot", False))
        total_closes = len(closed_rows)
        baseline_take_profit = _safe_float(self.config.get("tp"))
        base_order_amount = _safe_float(self.config.get("bo"))

        if not closed_rows:
            empty_state = self._build_default_state()
            empty_state.update(
                {
                    "enabled": enabled,
                    "baseline_mode_active": True,
                    "last_updated_at": now,
                }
            )
            return {"state": empty_state, "snapshots": []}

        global_duration_baseline = (
            sum(profitable_durations) / len(profitable_durations)
            if profitable_durations
            else 24.0
        )
        per_symbol_rows: dict[str, list[ClosedTradeMemoryRow]] = {}
        for row in closed_rows:
            per_symbol_rows.setdefault(row.symbol, []).append(row)

        snapshots: list[SymbolMemorySnapshot] = []
        for symbol, symbol_rows in per_symbol_rows.items():
            symbol_rows.sort(key=lambda row: row.close_date, reverse=True)
            sample_size = len(symbol_rows)
            confidence_progress = _clamp(
                sample_size / float(self.SYMBOL_CONFIDENT_CLOSES),
                0.0,
                1.0,
            )
            weighted_profit_sum = 0.0
            weight_total = 0.0
            weighted_speed_sum = 0.0
            weighted_duration_sum = 0.0
            profitable_closes = 0
            loss_count = 0
            slow_close_count = 0

            for trade in symbol_rows:
                age_days = max(
                    (_ensure_utc(now) - _ensure_utc(trade.close_date)).total_seconds()
                    / 86_400,
                    0.0,
                )
                weight = math.exp(-(age_days / self.DECAY_DAYS))
                normalized_profit = _clamp(trade.profit_percent / 2.0, -1.0, 1.0)
                weighted_profit_sum += normalized_profit * weight
                weight_total += weight
                if trade.profit >= 0:
                    profitable_closes += 1
                else:
                    loss_count += 1
                if trade.duration_hours is not None:
                    weighted_duration_sum += trade.duration_hours * weight
                    duration_score = (
                        global_duration_baseline - trade.duration_hours
                    ) / max(global_duration_baseline, 0.5)
                    weighted_speed_sum += _clamp(duration_score, -1.0, 1.0) * weight
                    if trade.duration_hours > (global_duration_baseline * 1.1):
                        slow_close_count += 1

            if weight_total <= 0:
                continue

            weighted_profit_signal = weighted_profit_sum / weight_total
            weighted_close_hours = (
                weighted_duration_sum / weight_total if weighted_duration_sum else 0.0
            )
            win_signal = (
                ((profitable_closes / sample_size) - 0.5) * 2.0 if sample_size else 0.0
            )
            speed_signal = (
                weighted_speed_sum / weight_total if weighted_speed_sum else 0.0
            )
            recent_losses = sum(
                1 for trade in symbol_rows[:2] if float(trade.profit or 0.0) < 0
            )
            stability_penalty = min(
                0.25 * recent_losses + 0.15 * max(slow_close_count - 1, 0),
                0.7,
            )
            raw_score = (
                0.45 * weighted_profit_signal
                + 0.30 * win_signal
                + 0.25 * speed_signal
                - stability_penalty
            )
            trust_score = 50.0 + (
                _clamp(raw_score, -1.0, 1.0) * 30.0 * confidence_progress
            )
            trust_score = round(_clamp(trust_score, 0.0, 100.0), 3)
            tp_delta_ratio = _clamp((trust_score - 50.0) / 20.0, -1.0, 1.0)

            if sample_size < self.MIN_SYMBOL_CLOSES:
                trust_direction = "neutral"
            elif trust_score >= 55:
                trust_direction = "favored"
            elif trust_score <= 45:
                trust_direction = "cooling"
            else:
                trust_direction = "neutral"

            primary_reason_code: str | None = None
            primary_reason_value: int | None = None
            secondary_reason_code: str | None = None
            secondary_reason_value: int | None = None

            if trust_direction == "favored":
                if speed_signal >= weighted_profit_signal and profitable_closes > 0:
                    primary_reason_code = "quick_profitable_closes"
                    primary_reason_value = profitable_closes
                else:
                    primary_reason_code = "strong_profit_quality"
                    primary_reason_value = profitable_closes
            elif trust_direction == "cooling":
                if slow_close_count > 0:
                    primary_reason_code = "slow_exits"
                    primary_reason_value = slow_close_count
                else:
                    primary_reason_code = "recent_losses"
                    primary_reason_value = max(loss_count, recent_losses)

            if sample_size < self.SYMBOL_CONFIDENT_CLOSES:
                secondary_reason_code = "thin_history"
                secondary_reason_value = sample_size
            elif trust_direction == "favored" and slow_close_count > 0:
                secondary_reason_code = "slow_exits"
                secondary_reason_value = slow_close_count
            elif trust_direction == "cooling" and profitable_closes > 0:
                secondary_reason_code = "quick_profitable_closes"
                secondary_reason_value = profitable_closes

            max_bo_delta = _base_order_delta_limit(
                base_order_amount,
                stretch_multiplier=_base_order_stretch_multiplier(self.config),
            )
            suggested_base_order = max(
                0.0,
                base_order_amount + tp_delta_ratio * max_bo_delta,
            )

            snapshots.append(
                SymbolMemorySnapshot(
                    symbol=symbol,
                    trust_score=trust_score,
                    trust_direction=trust_direction,
                    confidence_bucket=_confidence_bucket(sample_size),
                    confidence_progress=round(confidence_progress, 6),
                    sample_size=sample_size,
                    profitable_closes=profitable_closes,
                    loss_count=loss_count,
                    slow_close_count=slow_close_count,
                    weighted_profit_percent=round(weighted_profit_signal * 2.0, 6),
                    weighted_close_hours=round(weighted_close_hours, 6),
                    tp_delta_ratio=round(tp_delta_ratio, 6),
                    suggested_base_order=round(suggested_base_order, 8),
                    primary_reason_code=primary_reason_code,
                    primary_reason_value=primary_reason_value,
                    secondary_reason_code=secondary_reason_code,
                    secondary_reason_value=secondary_reason_value,
                    last_closed_at=symbol_rows[0].close_date,
                )
            )

        snapshots.sort(
            key=lambda snapshot: (
                snapshot.trust_direction != "favored",
                -abs(snapshot.trust_score - 50.0),
                -snapshot.trust_score,
                snapshot.symbol,
            )
        )

        featured_snapshot = snapshots[0] if snapshots else None
        favored_rows = [
            snapshot for snapshot in snapshots if snapshot.trust_direction == "favored"
        ]
        cooling_rows = [
            snapshot for snapshot in snapshots if snapshot.trust_direction == "cooling"
        ]

        if total_closes < required_closes:
            status = "warming_up"
        else:
            status = "fresh"

        state = {
            "status": status,
            "enabled": enabled,
            "stale_reason": None,
            "baseline_mode_active": (not enabled) or status != "fresh",
            "current_closes": total_closes,
            "required_closes": required_closes,
            "symbols_considered": len(snapshots),
            "trusted_symbols": len(favored_rows),
            "cooling_symbols": len(cooling_rows),
            "featured_symbol": featured_snapshot.symbol if featured_snapshot else None,
            "featured_direction": (
                featured_snapshot.trust_direction if featured_snapshot else None
            ),
            "featured_reason_code": (
                featured_snapshot.primary_reason_code if featured_snapshot else None
            ),
            "featured_reason_value": (
                featured_snapshot.primary_reason_value if featured_snapshot else None
            ),
            "adaptive_tp_min": (
                round(
                    baseline_take_profit - _tp_delta_limit(baseline_take_profit),
                    8,
                )
                if baseline_take_profit > 0
                else None
            ),
            "adaptive_tp_max": (
                round(
                    baseline_take_profit + _tp_delta_limit(baseline_take_profit),
                    8,
                )
                if baseline_take_profit > 0
                else None
            ),
            "suggested_base_order_min": (
                round(
                    max(
                        0.0,
                        base_order_amount
                        - _base_order_delta_limit(
                            base_order_amount,
                            stretch_multiplier=_base_order_stretch_multiplier(
                                self.config
                            ),
                        ),
                    ),
                    8,
                )
                if base_order_amount > 0
                else None
            ),
            "suggested_base_order_max": (
                round(
                    base_order_amount
                    + _base_order_delta_limit(
                        base_order_amount,
                        stretch_multiplier=_base_order_stretch_multiplier(self.config),
                    ),
                    8,
                )
                if base_order_amount > 0
                else None
            ),
            "last_updated_at": now,
            "last_success_at": now,
        }

        return {"state": state, "snapshots": snapshots}

    def _build_refresh_events(
        self,
        *,
        previous_state: dict[str, Any],
        previous_snapshots: dict[str, SymbolMemorySnapshot],
        next_state: dict[str, Any],
        next_snapshots: list[SymbolMemorySnapshot],
    ) -> list[MemoryEventCandidate]:
        """Build bounded event-log additions from a refreshed snapshot."""
        events: list[MemoryEventCandidate] = []
        next_featured = next_snapshots[0] if next_snapshots else None
        previous_featured = (
            previous_snapshots.get(str(previous_state.get("featured_symbol")))
            if previous_state.get("featured_symbol")
            else None
        )

        if (
            next_state["status"] == "warming_up"
            and previous_state.get("status") != "warming_up"
        ):
            events.append(
                MemoryEventCandidate(
                    event_type="memory_warming_up",
                    tone="info",
                    reason_code="thin_history",
                    reason_value=int(next_state["current_closes"]),
                )
            )
        if next_state["status"] == "fresh" and previous_state.get("status") != "fresh":
            events.append(
                MemoryEventCandidate(
                    event_type="memory_ready",
                    tone="success",
                )
            )

        if next_featured and (
            previous_featured is None
            or previous_featured.symbol != next_featured.symbol
            or previous_featured.trust_direction != next_featured.trust_direction
        ):
            if next_featured.trust_direction == "favored":
                events.append(
                    MemoryEventCandidate(
                        event_type="favored_symbol",
                        tone="success",
                        symbol=next_featured.symbol,
                        reason_code=next_featured.primary_reason_code,
                        reason_value=next_featured.primary_reason_value,
                        trust_score=next_featured.trust_score,
                    )
                )
            elif next_featured.trust_direction == "cooling":
                events.append(
                    MemoryEventCandidate(
                        event_type="cooling_symbol",
                        tone="warning",
                        symbol=next_featured.symbol,
                        reason_code=next_featured.primary_reason_code,
                        reason_value=next_featured.primary_reason_value,
                        trust_score=next_featured.trust_score,
                    )
                )

        return events[:3]
