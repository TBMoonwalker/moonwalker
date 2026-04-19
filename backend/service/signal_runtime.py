"""Shared helpers for signal plugin runtime settings, admission, and throttling."""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Sequence

import helper
import model
from service.autopilot import Autopilot
from service.autopilot_memory import AutopilotMemoryService, SymbolAdmissionProfile
from service.config import resolve_timeframe
from service.statistic import Statistic

logging = helper.LoggerFactory.get_logger("logs/signal.log", "signal_runtime")

_PENDING_ADMISSION_SYMBOLS: set[str] = set()
_PENDING_ADMISSION_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class CommonSignalRuntime:
    """Parsed runtime settings shared by signal plugins."""

    pair_denylist: list[str] | None
    pair_allowlist: list[str] | None
    volume: dict[str, Any] | None
    strategy_timeframe: str


@dataclass(frozen=True)
class SignalAdmissionDecision:
    """Explainable admission decision for one candidate symbol."""

    symbol: str
    admitted: bool
    reason_code: str
    memory_status: str
    trust_direction: str
    trust_score: float | None
    available_slots: int
    competing_candidates: int


class SignalAdmissionLease:
    """Process-local reservation handle for scarce slot admission."""

    def __init__(self, symbols: Sequence[str]) -> None:
        self._symbols = {
            _normalize_symbol(symbol) for symbol in symbols if _normalize_symbol(symbol)
        }

    async def release_symbol(self, symbol: str) -> None:
        """Release one previously reserved symbol slot."""
        normalized_symbol = _normalize_symbol(symbol)
        if not normalized_symbol:
            return
        async with _PENDING_ADMISSION_LOCK:
            self._symbols.discard(normalized_symbol)
            _PENDING_ADMISSION_SYMBOLS.discard(normalized_symbol)

    async def release(self) -> None:
        """Release all remaining reserved symbol slots."""
        async with _PENDING_ADMISSION_LOCK:
            for symbol in tuple(self._symbols):
                _PENDING_ADMISSION_SYMBOLS.discard(symbol)
            self._symbols.clear()

    async def __aenter__(self) -> "SignalAdmissionLease":
        """Return the lease for async-context use."""
        return self

    async def __aexit__(self, *_args: object) -> None:
        """Always release reservations on context exit."""
        await self.release()


@dataclass
class SignalAdmissionBatch:
    """Shared admission batch result for one plugin decision window."""

    decisions: list[SignalAdmissionDecision]
    lease: SignalAdmissionLease | None = None

    @property
    def admitted_symbols(self) -> list[str]:
        """Return admitted symbols in deterministic batch order."""
        return [decision.symbol for decision in self.decisions if decision.admitted]

    @property
    def has_capacity_block(self) -> bool:
        """Return whether any candidate lost due to slot saturation."""
        return any(
            decision.reason_code in {"skipped_capacity_full", "skipped_slot_reserved"}
            for decision in self.decisions
        )

    async def release_symbol(self, symbol: str) -> None:
        """Release one reserved symbol if a lease exists."""
        if self.lease is None:
            return
        await self.lease.release_symbol(symbol)

    async def release(self) -> None:
        """Release any remaining reservations for this batch."""
        if self.lease is None:
            return
        await self.lease.release()


def _normalize_symbol(value: Any) -> str:
    """Return a normalized symbol key for runtime comparisons."""
    return str(value or "").strip().upper()


def _parse_pair_list(raw_value: Any, *, token_only: bool) -> list[str] | None:
    """Parse optional pair lists while treating falsey sentinel values as empty."""
    if raw_value is None or raw_value is False:
        return None

    normalized = str(raw_value).strip()
    if not normalized or normalized.lower() in {"false", "none", "null"}:
        return None

    entries = [
        entry.strip().upper() for entry in normalized.split(",") if entry.strip()
    ]
    if token_only:
        return [entry.split("/")[0] for entry in entries] or None
    return entries or None


def parse_signal_settings(raw_value: Any) -> dict[str, Any]:
    """Parse signal settings from config string/dict payloads."""
    if isinstance(raw_value, dict):
        return raw_value
    if raw_value is None:
        return {}

    raw_text = str(raw_value).strip()
    if not raw_text:
        return {}

    parsed = json.loads(raw_text)

    if not isinstance(parsed, dict):
        raise TypeError("signal_settings must be a dictionary payload")

    return parsed


def build_common_runtime_settings(config: dict[str, Any]) -> CommonSignalRuntime:
    """Parse common signal runtime settings once per plugin run."""
    pair_denylist = _parse_pair_list(config.get("pair_denylist"), token_only=True)
    pair_allowlist = _parse_pair_list(config.get("pair_allowlist"), token_only=False)
    raw_volume = config.get("volume")
    volume = json.loads(raw_volume) if raw_volume else None
    strategy_timeframe = resolve_timeframe(config)
    return CommonSignalRuntime(
        pair_denylist=pair_denylist,
        pair_allowlist=pair_allowlist,
        volume=volume,
        strategy_timeframe=strategy_timeframe,
    )


def resolve_max_bots_log_interval(
    config: dict[str, Any], default_seconds: float = 60.0
) -> float:
    """Parse and clamp max-bots waiting log interval."""
    try:
        return max(1.0, float(config.get("max_bots_log_interval_sec", default_seconds)))
    except (TypeError, ValueError):
        return default_seconds


def update_waiting_log_state(
    blocked: bool, last_log: float, interval_seconds: float
) -> tuple[bool, float, bool]:
    """Return updated throttling state for max-bots waiting logs."""
    now = time.monotonic()
    should_log = (not blocked) or (now - last_log >= interval_seconds)
    if not should_log:
        return blocked, last_log, False
    return True, now, True


def _dedupe_candidate_symbols(candidate_symbols: Sequence[str]) -> list[str]:
    """Normalize and de-duplicate candidate symbols while preserving order."""
    deduped: list[str] = []
    seen: set[str] = set()
    for symbol in candidate_symbols:
        normalized_symbol = _normalize_symbol(symbol)
        if not normalized_symbol or normalized_symbol in seen:
            continue
        seen.add(normalized_symbol)
        deduped.append(normalized_symbol)
    return deduped


def _fallback_admission_profile(
    symbol: str,
    *,
    memory_status: str,
    reason_code: str | None,
) -> SymbolAdmissionProfile:
    """Build a neutral fallback profile when memory is unavailable."""
    return SymbolAdmissionProfile(
        symbol=symbol,
        memory_status=memory_status,
        trust_direction="neutral",
        trust_score=None,
        reason_code=reason_code,
        uses_trust_ranking=False,
    )


def _admission_sort_key(profile: SymbolAdmissionProfile) -> tuple[int, float, str]:
    """Return the deterministic sort key for scarce-slot admission."""
    if profile.uses_trust_ranking and profile.trust_direction == "favored":
        return (0, -(profile.trust_score or 0.0), profile.symbol)
    if profile.uses_trust_ranking and profile.trust_direction == "cooling":
        return (2, 0.0, profile.symbol)
    return (1, 0.0, profile.symbol)


def _admitted_reason_code(
    profile: SymbolAdmissionProfile,
    *,
    available_slots: int,
    competing_candidates: int,
) -> str:
    """Return the explanation code for an admitted symbol."""
    if available_slots >= competing_candidates:
        return "admitted_capacity_available"
    if not profile.uses_trust_ranking or profile.trust_direction == "neutral":
        return "admitted_fallback_order"
    if profile.trust_direction == "favored":
        return "admitted_trust_priority"
    return "admitted_cooling_capacity"


def log_signal_admission_decisions(
    decisions: Sequence[SignalAdmissionDecision],
) -> None:
    """Emit one shared log format for admitted and skipped candidates."""
    for decision in decisions:
        log_method = logging.info if decision.admitted else logging.debug
        log_method(
            "Signal admission %s for %s (reason=%s, memory_status=%s, trust_direction=%s, trust_score=%s, available_slots=%s, competing_candidates=%s).",
            "admitted" if decision.admitted else "skipped",
            decision.symbol,
            decision.reason_code,
            decision.memory_status,
            decision.trust_direction,
            decision.trust_score,
            decision.available_slots,
            decision.competing_candidates,
        )


async def get_active_open_symbols() -> list[str]:
    """Return active open-trade symbols excluding unsellable remnants."""
    open_trade_rows = await model.OpenTrades.all().values(
        "symbol",
        "unsellable_amount",
        "unsellable_reason",
    )
    active_symbols: list[str] = []
    for row in open_trade_rows:
        if float(row.get("unsellable_amount") or 0.0) > 0 and row.get(
            "unsellable_reason"
        ):
            continue
        symbol = _normalize_symbol(row.get("symbol"))
        if symbol:
            active_symbols.append(symbol)
    return active_symbols


async def _resolve_runtime_capacity(
    config: dict[str, Any],
    statistic: Statistic,
    autopilot: Autopilot,
) -> tuple[list[str], int]:
    """Return current active symbols and the effective max-bot limit."""
    max_bots = int(config.get("max_bots", 0) or 0)
    active_symbols = await get_active_open_symbols()
    profit = await statistic.get_profit()
    effective_max_bots = profit.get("autopilot_effective_max_bots")
    if effective_max_bots is None and config.get("autopilot", False):
        runtime_state = await autopilot.resolve_runtime_state(
            float(profit.get("funds_locked") or 0.0),
            config,
        )
        effective_max_bots = runtime_state["effective_max_bots"]
    return active_symbols, int(effective_max_bots or max_bots)


async def is_max_bots_reached(
    config: dict[str, Any],
    statistic: Statistic,
    autopilot: Autopilot,
) -> bool:
    """Return whether the configured max-bot limit currently blocks new trades."""
    active_symbols, effective_max_bots = await _resolve_runtime_capacity(
        config,
        statistic,
        autopilot,
    )
    return bool(active_symbols) and len(active_symbols) >= effective_max_bots


async def resolve_signal_admission_batch(
    config: dict[str, Any],
    statistic: Statistic,
    autopilot: Autopilot,
    candidate_symbols: Sequence[str],
) -> SignalAdmissionBatch:
    """Resolve ranked scarce-slot admission and reserve admitted symbols."""
    normalized_candidates = _dedupe_candidate_symbols(candidate_symbols)
    if not normalized_candidates:
        return SignalAdmissionBatch(decisions=[])

    async with _PENDING_ADMISSION_LOCK:
        active_symbols, effective_max_bots = await _resolve_runtime_capacity(
            config,
            statistic,
            autopilot,
        )
        active_symbol_set = set(active_symbols)
        reserved_symbol_set = set(_PENDING_ADMISSION_SYMBOLS)
        occupied_symbols = active_symbol_set | reserved_symbol_set
        available_slots = max(0, effective_max_bots - len(occupied_symbols))

        try:
            memory_service = await AutopilotMemoryService.instance()
            admission_profiles = memory_service.build_admission_profiles(
                normalized_candidates,
                enabled=bool(config.get("autopilot", False)),
            )
        except Exception as exc:  # noqa: BLE001 - fail open to stable fallback.
            logging.warning("Autopilot memory admission unavailable: %s", exc)
            admission_profiles = {
                symbol: _fallback_admission_profile(
                    symbol,
                    memory_status="stale",
                    reason_code="memory_unavailable",
                )
                for symbol in normalized_candidates
            }

        profiles: dict[str, SymbolAdmissionProfile] = {}
        for symbol in normalized_candidates:
            profiles[symbol] = admission_profiles.get(
                symbol
            ) or _fallback_admission_profile(
                symbol,
                memory_status="stale",
                reason_code="memory_unavailable",
            )

        ranked_candidates = sorted(
            [
                symbol
                for symbol in normalized_candidates
                if symbol not in active_symbol_set and symbol not in reserved_symbol_set
            ],
            key=lambda symbol: _admission_sort_key(profiles[symbol]),
        )
        competing_candidates = len(ranked_candidates)
        admitted_symbols = ranked_candidates[:available_slots]
        admitted_symbol_set = set(admitted_symbols)
        lease = None
        if admitted_symbols:
            _PENDING_ADMISSION_SYMBOLS.update(admitted_symbols)
            lease = SignalAdmissionLease(admitted_symbols)

        decisions: list[SignalAdmissionDecision] = []
        for symbol in normalized_candidates:
            profile = profiles[symbol]
            if symbol in active_symbol_set:
                admitted = False
                reason_code = "skipped_already_active"
            elif symbol in reserved_symbol_set:
                admitted = False
                reason_code = "skipped_slot_reserved"
            elif symbol in admitted_symbol_set:
                admitted = True
                reason_code = _admitted_reason_code(
                    profile,
                    available_slots=available_slots,
                    competing_candidates=competing_candidates,
                )
            elif available_slots <= 0:
                admitted = False
                reason_code = "skipped_capacity_full"
            else:
                admitted = False
                reason_code = "skipped_ranked_out"

            decisions.append(
                SignalAdmissionDecision(
                    symbol=symbol,
                    admitted=admitted,
                    reason_code=reason_code,
                    memory_status=profile.memory_status,
                    trust_direction=profile.trust_direction,
                    trust_score=profile.trust_score,
                    available_slots=available_slots,
                    competing_candidates=competing_candidates,
                )
            )

    return SignalAdmissionBatch(decisions=decisions, lease=lease)
