"""Shared trade-lifecycle close-reason constants and helpers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class TradeLifecycleMode(StrEnum):
    """Stable persistence values for mutually exclusive trade lifecycles."""

    CLASSIC_DCA = "classic_dca"


class TradeExposureState(StrEnum):
    """Stable persistence values for active trade exposure state."""

    LONG_EXPOSED = "long_exposed"


class TradeCloseReason(StrEnum):
    """Stable persistence values for closed-trade semantics."""

    TAKE_PROFIT = "take_profit"
    TRAILING_TAKE_PROFIT = "trailing_take_profit"
    STOP_LOSS = "stop_loss"
    AUTOPILOT_TIMEOUT = "autopilot_timeout"
    MANUAL_SELL = "manual_sell"
    MANUAL_STOP = "manual_stop"


TERMINAL_CLOSE_REASONS = frozenset(
    {
        TradeCloseReason.TAKE_PROFIT,
        TradeCloseReason.TRAILING_TAKE_PROFIT,
        TradeCloseReason.STOP_LOSS,
        TradeCloseReason.AUTOPILOT_TIMEOUT,
        TradeCloseReason.MANUAL_SELL,
        TradeCloseReason.MANUAL_STOP,
    }
)


def normalize_close_reason(value: Any) -> str:
    """Return a stable close-reason persistence value.

    Any unrecognized value falls back to take profit, the terminal default for a
    completed sell leg.
    """
    normalized = str(value or "").strip().lower()
    for reason in TradeCloseReason:
        if normalized == reason.value:
            return reason.value
    return TradeCloseReason.TAKE_PROFIT.value
