"""Read-only explanations of the exact completed-candle accumulation gates."""

from decimal import Decimal, localcontext
from typing import Any

from service.accumulation_strategy import (
    AccumulationGuard,
    AccumulationMarket,
    AccumulationObservations,
    AccumulationParameters,
    accumulation_correction_price,
    accumulation_decline_price,
    accumulation_recovery_price,
)


def accumulation_wait_condition(
    market: AccumulationMarket,
    state: AccumulationObservations,
    guard: AccumulationGuard | None,
    parameters: AccumulationParameters,
    reason: str,
) -> dict[str, Any] | None:
    """Explain the first unmet gate; levels are snapshots, never order promises."""
    with localcontext() as context:
        context.prec = 50
        price = Decimal(market.close)

        def level(kind: str, direction: str, target: Decimal) -> dict[str, str]:
            return {
                "kind": kind,
                "direction": direction,
                "target_price": str(target),
                "change_percent": str((target - price) / price * 100),
            }

        levels: list[dict[str, str]] = []
        if reason == "WAIT_DECLINE":
            levels.append(level("decline", "below", Decimal(market.previous_close)))
        elif reason == "WAIT_DEPTH":
            target = Decimal(market.peak) - Decimal(parameters.entry_atr) * Decimal(
                market.atr
            )
            if target > 0:
                levels.append(level("depth", "at_or_below", target))
        elif reason == "WAIT_REARM" and guard is not None:
            if market.close_ms > guard.signal_close_ms:
                further = accumulation_decline_price(market, guard, parameters)
                if state.recovery_ready:
                    assert state.high_close is not None
                    assert state.atr_at_high is not None
                    correction = accumulation_correction_price(state, parameters)
                    target = max(further, correction)
                    if target > 0:
                        levels.append(level("correction", "at_or_below", target))
                else:
                    if further > 0:
                        levels.append(level("further_decline", "at_or_below", further))
                    recovery = accumulation_recovery_price(market, guard, parameters)
                    levels.append(
                        level("recovery_then_correction", "at_or_above", recovery)
                    )
        elif reason not in {"WAIT_BASELINE", "WAIT_NEW_CANDLE", "WAIT_CONDITIONS"}:
            return None
        result: dict[str, Any] = {
            "reason": reason,
            "timeframe": parameters.timeframe,
            "observed_close_ms": market.close_ms,
            "observed_price": market.close,
            "next_close_ms": market.close_ms + parameters.interval_ms,
            "levels": levels,
        }

        if reason == "WAIT_BASELINE":
            # A next-bar estimate uses the latest close as the decline boundary.
            # Indicators are frozen here; actual admission recalculates at close.
            target = min(
                price,
                Decimal(market.peak)
                - Decimal(parameters.entry_atr) * Decimal(market.atr),
            )
            if guard is not None:
                rearm = accumulation_decline_price(market, guard, parameters)
                if state.recovery_ready:
                    assert (
                        state.high_close is not None and state.atr_at_high is not None
                    )
                    rearm = max(
                        rearm,
                        accumulation_correction_price(state, parameters),
                    )
                target = min(target, rearm)
            if target > 0:
                result["indicative"] = {
                    "level": level(
                        "dip", "below" if target == price else "at_or_below", target
                    ),
                    "conditions_match": market.conditions_match,
                }
        return result
