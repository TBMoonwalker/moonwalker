"""Helpers for DCA take-profit runtime state."""

from typing import Protocol, TypedDict


class LoggerLike(Protocol):
    """Logger interface used by TP state helpers."""

    def info(self, msg: str, *args: object) -> None:
        """Log informational TP state transitions."""

    def debug(self, msg: str, *args: object) -> None:
        """Log verbose TP state transitions."""


class TpConfirmationState(TypedDict):
    """In-memory TP confirmation state for a single open trade."""

    started_at: float
    qualifying_ticks: int
    peak_price: float
    tp_price: float
    trade_timestamp: int


def clear_tp_confirmation(
    pending_states: dict[str, TpConfirmationState],
    *,
    logger: LoggerLike,
    symbol: str,
    reason: str,
    current_price: float | None = None,
    tp_price: float | None = None,
) -> None:
    """Clear pending TP confirmation state and log why it was removed."""
    state = pending_states.pop(symbol, None)
    if state is None:
        return

    logger.info(
        "Cleared TP confirmation for %s: reason=%s current_price=%s tp_price=%s "
        "peak_price=%s qualifying_ticks=%s",
        symbol,
        reason,
        (round(float(current_price), 10) if current_price is not None else "n/a"),
        round(float(tp_price or state["tp_price"]), 10),
        round(float(state["peak_price"]), 10),
        int(state["qualifying_ticks"]),
    )


def evaluate_tp_confirmation(
    pending_states: dict[str, TpConfirmationState],
    *,
    logger: LoggerLike,
    now: float,
    symbol: str,
    trade_timestamp: int,
    current_price: float,
    tp_price: float,
    seconds_required: float,
    ticks_required: int,
) -> bool:
    """Return whether TP remained above threshold long enough to sell."""
    if seconds_required <= 0 and ticks_required <= 0:
        return True

    state = pending_states.get(symbol)
    if state and state["trade_timestamp"] != trade_timestamp:
        clear_tp_confirmation(
            pending_states,
            logger=logger,
            symbol=symbol,
            reason="trade_changed",
            current_price=current_price,
            tp_price=tp_price,
        )
        state = None

    if state and abs(state["tp_price"] - tp_price) > 1e-12:
        clear_tp_confirmation(
            pending_states,
            logger=logger,
            symbol=symbol,
            reason="tp_price_changed",
            current_price=current_price,
            tp_price=tp_price,
        )
        state = None

    if state is None:
        pending_states[symbol] = {
            "started_at": now,
            "qualifying_ticks": 1,
            "peak_price": current_price,
            "tp_price": tp_price,
            "trade_timestamp": trade_timestamp,
        }
        logger.info(
            "Started TP confirmation for %s: current_price=%s tp_price=%s "
            "seconds_required=%s ticks_required=%s",
            symbol,
            round(current_price, 10),
            round(tp_price, 10),
            round(seconds_required, 4),
            ticks_required,
        )
        return False

    state["qualifying_ticks"] += 1
    state["peak_price"] = max(float(state["peak_price"]), current_price)

    elapsed = now - float(state["started_at"])
    seconds_met = seconds_required <= 0 or elapsed >= seconds_required
    ticks_met = ticks_required <= 0 or state["qualifying_ticks"] >= ticks_required
    if seconds_met and ticks_met:
        pending_states.pop(symbol, None)
        logger.info(
            "TP confirmation passed for %s: current_price=%s tp_price=%s "
            "elapsed=%.4f qualifying_ticks=%s peak_price=%s",
            symbol,
            round(current_price, 10),
            round(tp_price, 10),
            elapsed,
            int(state["qualifying_ticks"]),
            round(float(state["peak_price"]), 10),
        )
        return True

    logger.debug(
        "Waiting for TP confirmation on %s: current_price=%s tp_price=%s "
        "elapsed=%.4f qualifying_ticks=%s seconds_required=%s ticks_required=%s",
        symbol,
        round(current_price, 10),
        round(tp_price, 10),
        elapsed,
        int(state["qualifying_ticks"]),
        round(seconds_required, 4),
        ticks_required,
    )
    return False


def get_tp_confirmation_ticks(
    pending_states: dict[str, TpConfirmationState],
    symbol: str,
) -> tuple[bool, int]:
    """Return whether TP confirmation is pending and how many ticks qualified."""
    pending_state = pending_states.get(symbol)
    if pending_state is None:
        return False, 0
    return True, int(pending_state["qualifying_ticks"])


def apply_trailing_take_profit(
    trailing_tp_peaks: dict[str, float],
    *,
    logger: LoggerLike,
    symbol: str,
    actual_pnl: float,
    trailing_tp: float,
    take_profit: float,
    sell_signal: bool,
) -> bool:
    """Apply trailing take-profit state and return the updated sell decision."""
    if not sell_signal and symbol not in trailing_tp_peaks:
        return sell_signal

    if symbol not in trailing_tp_peaks:
        trailing_tp_peaks[symbol] = 0.0

    if actual_pnl != trailing_tp_peaks[symbol] and trailing_tp_peaks[symbol] != 0.0:
        diff = actual_pnl - trailing_tp_peaks[symbol]

        logger.debug(
            "TTP Check: %s - Actual PNL: %s, Top-PNL: %s, PNL Difference: %s",
            symbol,
            actual_pnl,
            trailing_tp_peaks[symbol],
            diff,
        )

        if (diff < 0 and abs(diff) > trailing_tp) or (
            actual_pnl < take_profit and actual_pnl > trailing_tp
        ):
            logger.debug(
                "TTP Sell: %s - Percentage decreased - Take profit with difference: %s",
                symbol,
                diff,
            )
            trailing_tp_peaks.pop(symbol)
            return True

        if actual_pnl > trailing_tp_peaks[symbol]:
            trailing_tp_peaks[symbol] = actual_pnl
        return False

    trailing_tp_peaks[symbol] = actual_pnl
    return False
