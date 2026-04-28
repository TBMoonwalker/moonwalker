"""Pure analytics and guardrail helpers for Green Phase runtime decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from service.trade_math import parse_date_to_ms


@dataclass(frozen=True)
class GreenPhaseSettings:
    """Normalized configuration that drives Green Phase behavior."""

    enabled: bool
    eval_interval_seconds: float
    ramp_days: int
    recent_window_minutes: int
    confirm_cycles: int
    release_cycles: int
    speed_multiplier: float
    exit_multiplier: float
    min_profitable_close_ratio: float
    max_extra_deals: int
    max_locked_fund_percent: float
    capital_max_fund: float
    base_order_size: float


@dataclass(frozen=True)
class GreenPhaseAnalysisResult:
    """Computed Green Phase analytics for the current evaluation window."""

    ramp_ready: bool
    green_phase_detected: bool
    phase_strength: float
    baseline_profitable_closes_per_hour: float
    recent_profitable_closes_per_hour: float
    recent_profitable_close_ratio: float
    recent_total_closes: int
    recent_profitable_closes: int
    recommended_extra_deals: int
    guardrail_block_reason: str | None


def to_int(value: Any, default: int) -> int:
    """Normalize integer config values with fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float) -> float:
    """Normalize float config values with fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_green_phase_enabled(config: dict[str, Any]) -> bool:
    """Return True when Autopilot and Green Phase are both enabled."""
    return bool(config.get("autopilot")) and bool(
        config.get("autopilot_green_phase_enabled")
    )


def build_green_phase_settings(config: dict[str, Any]) -> GreenPhaseSettings:
    """Build normalized Green Phase settings from the raw config snapshot."""
    return GreenPhaseSettings(
        enabled=is_green_phase_enabled(config),
        eval_interval_seconds=max(
            5.0,
            to_float(config.get("autopilot_green_phase_eval_interval_sec"), 60.0),
        ),
        ramp_days=max(1, to_int(config.get("autopilot_green_phase_ramp_days"), 30)),
        recent_window_minutes=max(
            5,
            to_int(config.get("autopilot_green_phase_window_minutes"), 60),
        ),
        confirm_cycles=max(
            1,
            to_int(config.get("autopilot_green_phase_confirm_cycles"), 2),
        ),
        release_cycles=max(
            1,
            to_int(config.get("autopilot_green_phase_release_cycles"), 4),
        ),
        speed_multiplier=to_float(
            config.get("autopilot_green_phase_speed_multiplier"),
            1.5,
        ),
        exit_multiplier=to_float(
            config.get("autopilot_green_phase_exit_multiplier"),
            1.15,
        ),
        min_profitable_close_ratio=to_float(
            config.get("autopilot_green_phase_min_profitable_close_ratio"),
            0.8,
        ),
        max_extra_deals=max(
            0,
            to_int(config.get("autopilot_green_phase_max_extra_deals"), 2),
        ),
        max_locked_fund_percent=to_float(
            config.get("autopilot_green_phase_max_locked_fund_percent"),
            85.0,
        ),
        capital_max_fund=to_float(config.get("capital_max_fund"), 0.0),
        base_order_size=max(0.0, to_float(config.get("bo"), 0.0)),
    )


def analyze_green_phase_rows(
    rows: Iterable[tuple[Any, Any]],
    *,
    now: datetime,
    settings: GreenPhaseSettings,
    current_detected: bool,
    confirm_counter: int,
    release_counter: int,
    min_ramp_total_closes: int,
    min_ramp_profitable_closes: int,
    min_recent_profitable_closes: int,
) -> tuple[GreenPhaseAnalysisResult, int, int]:
    """Analyze closed-trade rows and derive the next Green Phase state."""
    ramp_cutoff = now - timedelta(days=settings.ramp_days)
    recent_cutoff = now - timedelta(minutes=settings.recent_window_minutes)

    parsed_rows: list[tuple[datetime, float]] = []
    for close_date, profit in rows:
        close_ms = parse_date_to_ms(str(close_date or ""))
        if close_ms is None:
            continue
        close_dt = datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc)
        if close_dt < ramp_cutoff:
            continue
        parsed_rows.append((close_dt, float(profit or 0.0)))

    ramp_total = len(parsed_rows)
    ramp_profitable = sum(1 for _, profit in parsed_rows if profit > 0)
    recent_rows = [
        (close_dt, profit)
        for close_dt, profit in parsed_rows
        if close_dt >= recent_cutoff
    ]
    recent_total = len(recent_rows)
    recent_profitable = sum(1 for _, profit in recent_rows if profit > 0)

    ramp_hours = max(float(settings.ramp_days) * 24.0, 1.0)
    recent_hours = max(float(settings.recent_window_minutes) / 60.0, 1.0 / 12.0)
    baseline_speed = float(ramp_profitable) / ramp_hours
    recent_speed = float(recent_profitable) / recent_hours
    recent_ratio = (
        float(recent_profitable) / float(recent_total) if recent_total > 0 else 0.0
    )
    ramp_ready = (
        ramp_total >= min_ramp_total_closes
        and ramp_profitable >= min_ramp_profitable_closes
        and baseline_speed > 0
    )

    detected = False
    recommended_extra_deals = 0
    phase_strength = 0.0

    if ramp_ready:
        phase_strength = recent_speed / baseline_speed if baseline_speed > 0 else 0.0
        enter_candidate = (
            recent_profitable >= min_recent_profitable_closes
            and recent_speed >= baseline_speed * max(settings.speed_multiplier, 1.0)
            and recent_ratio >= settings.min_profitable_close_ratio
        )
        exit_candidate = (
            recent_total == 0
            or recent_speed < baseline_speed * max(settings.exit_multiplier, 0.5)
            or recent_ratio < settings.min_profitable_close_ratio
        )

        if current_detected:
            confirm_counter = 0
            if exit_candidate:
                release_counter += 1
                if release_counter >= settings.release_cycles:
                    detected = False
                    release_counter = 0
                else:
                    detected = True
            else:
                release_counter = 0
                detected = True
        else:
            release_counter = 0
            if enter_candidate:
                confirm_counter += 1
                if confirm_counter >= settings.confirm_cycles:
                    detected = True
                    confirm_counter = 0
            else:
                confirm_counter = 0

        if detected and settings.max_extra_deals > 0:
            recommended_extra_deals = min(
                settings.max_extra_deals,
                max(1, int(phase_strength / max(settings.speed_multiplier, 0.1))),
            )
    else:
        confirm_counter = 0
        release_counter = 0

    return (
        GreenPhaseAnalysisResult(
            ramp_ready=ramp_ready,
            green_phase_detected=detected,
            phase_strength=round(phase_strength, 4),
            baseline_profitable_closes_per_hour=round(baseline_speed, 6),
            recent_profitable_closes_per_hour=round(recent_speed, 6),
            recent_profitable_close_ratio=round(recent_ratio, 6),
            recent_total_closes=recent_total,
            recent_profitable_closes=recent_profitable,
            recommended_extra_deals=recommended_extra_deals,
            guardrail_block_reason=("ramp_not_ready" if not ramp_ready else None),
        ),
        confirm_counter,
        release_counter,
    )


def build_green_phase_state(
    analysis: GreenPhaseAnalysisResult,
    *,
    evaluated_at: datetime,
) -> dict[str, Any]:
    """Convert Green Phase analytics into the persisted runtime state shape."""
    return {
        "enabled": True,
        "ramp_ready": analysis.ramp_ready,
        "green_phase_detected": analysis.green_phase_detected,
        "green_phase_active": False,
        "phase_strength": analysis.phase_strength,
        "baseline_profitable_closes_per_hour": (
            analysis.baseline_profitable_closes_per_hour
        ),
        "recent_profitable_closes_per_hour": analysis.recent_profitable_closes_per_hour,
        "recent_profitable_close_ratio": analysis.recent_profitable_close_ratio,
        "recent_total_closes": analysis.recent_total_closes,
        "recent_profitable_closes": analysis.recent_profitable_closes,
        "recommended_extra_deals": analysis.recommended_extra_deals,
        "effective_extra_deals": 0,
        "effective_max_bots": 0,
        "guardrail_block_reason": analysis.guardrail_block_reason,
        "last_evaluated_at": evaluated_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_green_phase_override_base(
    state: dict[str, Any],
    *,
    base_max_bots: int,
) -> dict[str, Any]:
    """Build the default override payload before guardrail evaluation."""
    return {
        **state,
        "green_phase_active": False,
        "effective_extra_deals": 0,
        "effective_max_bots": max(0, int(base_max_bots or 0)),
        "guardrail_block_reason": state.get("guardrail_block_reason"),
    }


def should_evaluate_green_phase_guardrails(
    state: dict[str, Any],
    settings: GreenPhaseSettings,
) -> bool:
    """Return whether Green Phase guardrails should be evaluated."""
    return (
        settings.enabled
        and bool(state.get("ramp_ready"))
        and bool(state.get("green_phase_detected"))
    )


def apply_green_phase_guardrails(
    result: dict[str, Any],
    *,
    settings: GreenPhaseSettings,
    funds_locked: float,
    base_max_bots: int,
    current_reserve: float,
    full_trade_budget: float,
    available_quote: float | None,
) -> dict[str, Any]:
    """Apply Green Phase reserve and locked-fund guardrails."""
    evaluated = dict(result)
    max_extra_deals = min(
        max(0, int(evaluated.get("recommended_extra_deals") or 0)),
        settings.max_extra_deals,
    )
    if max_extra_deals <= 0:
        evaluated["guardrail_block_reason"] = "no_extra_deals_configured"
        return evaluated

    if full_trade_budget <= 0:
        evaluated["guardrail_block_reason"] = "invalid_trade_budget"
        return evaluated

    if available_quote is None:
        evaluated["guardrail_block_reason"] = "balance_unavailable"
        return evaluated

    evaluated["guardrail_block_reason"] = "reserve_shortfall"

    for extra_deals in range(max_extra_deals, 0, -1):
        if settings.capital_max_fund > 0 and settings.base_order_size > 0:
            projected_locked_percent = (
                (float(funds_locked) + settings.base_order_size * extra_deals)
                / settings.capital_max_fund
            ) * 100
            if projected_locked_percent > settings.max_locked_fund_percent:
                evaluated["guardrail_block_reason"] = "locked_fund_guardrail"
                continue

        required_quote = current_reserve + full_trade_budget * extra_deals
        if available_quote + 1e-12 < required_quote:
            evaluated["guardrail_block_reason"] = "reserve_shortfall"
            continue

        evaluated["green_phase_active"] = True
        evaluated["effective_extra_deals"] = extra_deals
        evaluated["effective_max_bots"] = max(0, int(base_max_bots or 0) + extra_deals)
        evaluated["guardrail_block_reason"] = None
        return evaluated

    return evaluated
