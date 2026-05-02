"""Shared spot sidestep campaign types and constants."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class TradeLifecycleMode(StrEnum):
    """Stable persistence values for mutually exclusive trade lifecycles."""

    CLASSIC_DCA = "classic_dca"
    SIDESTEP_REENTRY = "sidestep_reentry"


class TradeExposureState(StrEnum):
    """Stable persistence values for active trade exposure state."""

    LONG_EXPOSED = "long_exposed"
    FLAT_WAITING_REENTRY = "flat_waiting_reentry"


class SpotCampaignState(StrEnum):
    """Stable persistence values for sidestep campaign state."""

    ACTIVE_LONG = "active_long"
    FLAT_WAITING_REENTRY = "flat_waiting_reentry"
    COMPLETED_TP = "completed_tp"
    STOPPED = "stopped"


class TradeCloseReason(StrEnum):
    """Stable persistence values for closed-trade semantics."""

    TAKE_PROFIT = "take_profit"
    TRAILING_TAKE_PROFIT = "trailing_take_profit"
    STOP_LOSS = "stop_loss"
    AUTOPILOT_TIMEOUT = "autopilot_timeout"
    SIDESTEP_EXIT = "sidestep_exit"
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

NON_TERMINAL_CLOSE_REASONS = frozenset({TradeCloseReason.SIDESTEP_EXIT})

NON_TERMINAL_CLOSE_REASON_VALUES = tuple(
    reason.value for reason in NON_TERMINAL_CLOSE_REASONS
)


def is_non_terminal_close_reason(value: Any) -> bool:
    """Return whether a close reason represents an ongoing campaign transition."""
    return str(value or "").strip().lower() in NON_TERMINAL_CLOSE_REASON_VALUES
