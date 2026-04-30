"""Shared spot sidestep campaign types and constants."""

from __future__ import annotations

from enum import StrEnum


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
