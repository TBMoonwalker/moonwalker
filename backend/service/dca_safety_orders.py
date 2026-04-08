"""Helpers for DCA safety-order progression."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SafetyOrderContext:
    """Derived safety-order context for the current trade."""

    last_so_price: float
    safety_order_size: float
    next_so_percentage: float
    trigger_threshold: float
    last_so_percentage: float | None


def calculate_static_deviations(
    step_scale: float,
    price_deviation: float,
    safetyorders_count: int,
) -> tuple[float, float]:
    """Calculate max and actual deviation for static DCA progression."""
    if step_scale == 1:
        max_deviation = price_deviation * (safetyorders_count + 1)
        actual_deviation = price_deviation * safetyorders_count
        return max_deviation, actual_deviation

    max_deviation = (price_deviation * (1 - step_scale ** (safetyorders_count + 1))) / (
        1 - step_scale
    )
    max_deviation = round(max_deviation, 2)
    actual_deviation = (price_deviation * (1 - step_scale**safetyorders_count)) / (
        1 - step_scale
    )
    return max_deviation, actual_deviation


def derive_safety_order_context(
    *,
    safetyorders: list[dict[str, Any]],
    max_safety_orders: int,
    volume_scale: float,
    step_scale: float,
    price_deviation: float,
    safety_order_size: float,
    next_so_percentage: float,
    trigger_threshold: float,
) -> SafetyOrderContext:
    """Derive safety-order thresholds from already placed orders."""
    last_so_price = 0.0
    if safetyorders and max_safety_orders:
        safety_order_size = safetyorders[-1]["ordersize"] * volume_scale
        next_so_percentage = float(safetyorders[-1]["so_percentage"]) * step_scale
        if len(safetyorders) >= 2:
            next_so_percentage = -abs(next_so_percentage) + -abs(
                float(safetyorders[-2]["so_percentage"])
            )
        else:
            next_so_percentage = -abs(next_so_percentage) + -abs(price_deviation)
        trigger_threshold = -abs(next_so_percentage)
        last_so_price = float(safetyorders[-1]["price"])

    last_so_percentage: float | None = None
    if safetyorders:
        so_values = [
            float(so["so_percentage"])
            for so in safetyorders
            if so.get("so_percentage") is not None
        ]
        if so_values:
            last_so_percentage = min(so_values)

    return SafetyOrderContext(
        last_so_price=last_so_price,
        safety_order_size=safety_order_size,
        next_so_percentage=next_so_percentage,
        trigger_threshold=trigger_threshold,
        last_so_percentage=last_so_percentage,
    )


def evaluate_static_dca_trigger(
    total_pnl: float,
    max_deviation: float,
    actual_deviation: float,
) -> tuple[bool, float, float]:
    """Return whether static DCA should open a new safety order."""
    new_so = False
    trigger_threshold = -abs(max_deviation - actual_deviation)
    next_so_percentage = 0.0
    if total_pnl <= -abs(max_deviation):
        next_so_percentage = max_deviation - actual_deviation
        next_so_percentage = round(next_so_percentage, 2)
        trigger_threshold = -abs(next_so_percentage)
        new_so = True
    return new_so, trigger_threshold, next_so_percentage
