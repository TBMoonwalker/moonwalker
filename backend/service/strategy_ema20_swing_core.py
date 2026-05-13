"""Shared EMA20 swing strategy mechanics."""

from __future__ import annotations

from typing import Any

import talib
from service.database import run_sqlite_write_with_retry
from service.indicators import Indicators
from tortoise.exceptions import BaseORMException, ConfigurationError

EMA20_LOOKBACK_LENGTH = 50
EMA20_REQUIRED_CLOSED_CANDLES = 22


class BaseEma20SwingStrategy:
    """Shared EMA20 swing skeleton for bullish and reverse variants."""

    state_model: Any = None
    state_version_suffix = ""
    strategy_display_name = "EMA20 swing"
    trend_key = "ema20_rising"
    price_position_key = "closed_above_ema20"

    def __init__(
        self,
        timeframe: str,
        btc_pulse: Any | None = None,
        *,
        logger: Any,
    ) -> None:
        del btc_pulse
        self.timeframe = timeframe
        self._state_timeframe = f"{timeframe}{self.state_version_suffix}"
        self.indicators = Indicators()
        self._logger = logger
        self._last_log_by_symbol: dict[str, dict[str, Any]] = {}
        self._previous_state_by_symbol: dict[str, tuple[float, float]] = {}

    def _emit_debug_state(self, symbol: str, payload: dict[str, Any]) -> None:
        """Write one structured debug line per symbol state change."""
        if self._last_log_by_symbol.get(symbol) == payload:
            return
        self._logger.debug("%s", payload)
        self._last_log_by_symbol[symbol] = payload.copy()

    @staticmethod
    def _is_missing_number(value: Any) -> bool:
        """Return True when a numeric value is missing or NaN."""
        return value is None or value != value

    def _ema_trend_matches(
        self,
        current_ema20_value: float,
        previous_ema20_value: float,
    ) -> bool:
        """Return whether the EMA20 slope matches the strategy direction."""
        raise NotImplementedError

    def _close_position_matches(
        self,
        close_value: float,
        ema20_value: float,
    ) -> bool:
        """Return whether the close sits on the correct side of EMA20."""
        raise NotImplementedError

    async def _load_indicator_inputs(self, symbol: str) -> tuple[dict[str, Any], Any]:
        """Load EMA and close-price inputs for one strategy evaluation."""
        raise NotImplementedError

    @classmethod
    def _build_ema20_series(cls, close_series: Any) -> Any:
        """Build the EMA20 series from the provided close history."""
        return talib.EMA(close_series, timeperiod=20)

    def _evaluate_trigger_candidate(
        self,
        *,
        close_value: Any,
        ema20_value: Any,
        previous_ema20_value: Any,
    ) -> tuple[bool, float | None, float | None]:
        """Return the trigger flag plus the candidate closed-candle state."""
        raw_values = (close_value, ema20_value, previous_ema20_value)
        if any(self._is_missing_number(value) for value in raw_values):
            return False, None, None

        close_value_float = float(close_value)
        ema20_value_float = float(ema20_value)
        previous_ema20_value_float = float(previous_ema20_value)

        trigger = self._ema_trend_matches(
            ema20_value_float,
            previous_ema20_value_float,
        ) and self._close_position_matches(close_value_float, ema20_value_float)
        return trigger, close_value_float, ema20_value_float

    def _find_latest_qualified_state_from_series(
        self,
        close_series: Any,
        ema20_series: Any,
    ) -> tuple[float, float] | None:
        """Return the latest qualifying closed-candle state from history."""
        latest_state: tuple[float, float] | None = None
        for idx in range(1, len(close_series)):
            trigger, close_value, ema20_value = self._evaluate_trigger_candidate(
                close_value=close_series.iloc[idx],
                ema20_value=ema20_series.iloc[idx],
                previous_ema20_value=ema20_series.iloc[idx - 1],
            )
            if trigger and close_value is not None and ema20_value is not None:
                latest_state = (close_value, ema20_value)
        return latest_state

    def _bootstrap_previous_state_from_history(
        self,
        close_series: Any,
    ) -> tuple[float, float] | None:
        """Reconstruct the latest qualifying state from stored candle history."""
        ema20_series = self._build_ema20_series(close_series)
        return self._find_latest_qualified_state_from_series(
            close_series,
            ema20_series,
        )

    async def _load_persisted_state(
        self,
        symbol: str,
    ) -> tuple[float, float] | None:
        """Load the last qualifying closed-candle state from persistent storage."""
        try:
            row = await self.state_model.get_or_none(
                symbol=symbol,
                timeframe=self._state_timeframe,
            )
        except (
            BaseORMException,
            ConfigurationError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            self._logger.error(
                "Cannot load persisted %s state for %s on %s: %s",
                self.strategy_display_name.lower(),
                symbol,
                self.timeframe,
                exc,
                exc_info=True,
            )
            return None

        if row is None:
            return None
        return (float(row.previous_swing_low), float(row.previous_ema20))

    async def _persist_previous_state(
        self,
        symbol: str,
        close_value: float,
        ema20_value: float,
    ) -> None:
        """Persist the latest qualifying state for restart-safe recovery."""

        async def _persist() -> None:
            await self.state_model.update_or_create(
                defaults={
                    "previous_swing_low": close_value,
                    "previous_ema20": ema20_value,
                },
                symbol=symbol,
                timeframe=self._state_timeframe,
            )

        try:
            await run_sqlite_write_with_retry(
                _persist,
                (
                    f"persisting {self.strategy_display_name.lower()} state "
                    f"for {symbol} on {self.timeframe}"
                ),
            )
        except (
            BaseORMException,
            ConfigurationError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            self._logger.error(
                "Cannot persist %s state for %s on %s: %s",
                self.strategy_display_name.lower(),
                symbol,
                self.timeframe,
                exc,
                exc_info=True,
            )

    async def _remember_previous_state(
        self,
        symbol: str,
        close_value: float,
        ema20_value: float,
    ) -> None:
        """Update process-local and persisted restart state."""
        self._previous_state_by_symbol[symbol] = (close_value, ema20_value)
        await self._persist_previous_state(symbol, close_value, ema20_value)

    async def _resolve_previous_state(
        self,
        symbol: str,
        close_series: Any,
    ) -> tuple[tuple[float, float] | None, bool]:
        """Return the prior state and whether it was bootstrapped."""
        if symbol in self._previous_state_by_symbol:
            return self._previous_state_by_symbol[symbol], False

        persisted_state = await self._load_persisted_state(symbol)
        if persisted_state is not None:
            self._previous_state_by_symbol[symbol] = persisted_state
            return persisted_state, False

        bootstrapped_state = self._bootstrap_previous_state_from_history(close_series)
        if bootstrapped_state is None:
            return None, False

        await self._remember_previous_state(
            symbol,
            bootstrapped_state[0],
            bootstrapped_state[1],
        )
        return bootstrapped_state, True

    async def run(self, symbol: str, type: str) -> bool:
        """Evaluate EMA20 directional progression for a symbol."""
        del type
        result = False
        ema, close = await self._load_indicator_inputs(symbol)

        try:
            if ema.get("ema_20") is None:
                self._emit_debug_state(
                    symbol,
                    {
                        "symbol": symbol,
                        "reason": "ema20_unavailable",
                        "creating_order": False,
                    },
                )
                return False
            if close is None:
                self._emit_debug_state(
                    symbol,
                    {
                        "symbol": symbol,
                        "reason": "close_series_unavailable",
                        "ema20(current)": ema.get("ema_20"),
                        "creating_order": False,
                    },
                )
                return False
            close_series = close.dropna()
            if len(close_series) < EMA20_REQUIRED_CLOSED_CANDLES:
                self._emit_debug_state(
                    symbol,
                    {
                        "symbol": symbol,
                        "reason": "insufficient_closed_candles",
                        "ema20(current)": ema.get("ema_20"),
                        "available_closed_candles": int(len(close_series)),
                        "required_closed_candles": EMA20_REQUIRED_CLOSED_CANDLES,
                        "creating_order": False,
                    },
                )
                return False

            ema20_series = self._build_ema20_series(close_series)
            trigger, latest_closed_value, latest_closed_ema20 = (
                self._evaluate_trigger_candidate(
                    close_value=close_series.iloc[-1],
                    ema20_value=ema20_series.iloc[-1],
                    previous_ema20_value=ema20_series.iloc[-2],
                )
            )
            previous_state, bootstrapped = await self._resolve_previous_state(
                symbol,
                close_series,
            )
            previous_close_value = previous_state[0] if previous_state else None
            previous_ema20 = previous_state[1] if previous_state else None

            if (
                trigger
                and latest_closed_value is not None
                and latest_closed_ema20 is not None
            ):
                if (
                    previous_state is not None
                    and not bootstrapped
                    and previous_close_value is not None
                    and previous_ema20 is not None
                ):
                    result = (
                        latest_closed_value != previous_close_value
                        or latest_closed_ema20 != previous_ema20
                    )
                if previous_state != (latest_closed_value, latest_closed_ema20):
                    await self._remember_previous_state(
                        symbol,
                        latest_closed_value,
                        latest_closed_ema20,
                    )

            logging_json = {
                "symbol": symbol,
                "close(previous_closed/latest_closed)": (
                    f"{close_series.iloc[-2]} / {close_series.iloc[-1]}"
                ),
                "ema20(previous_closed/latest_closed)": (
                    f"{ema20_series.iloc[-2]} / {ema['ema_20']}"
                ),
                "ema20(previous_closed)": ema20_series.iloc[-2],
                "trigger_close(latest_closed)": (
                    latest_closed_value if trigger else None
                ),
                "trigger_close(previous)": previous_close_value,
                "ema20(closed)": latest_closed_ema20,
                "ema20(previous_trigger)": previous_ema20,
                self.trend_key: (
                    None
                    if self._is_missing_number(ema20_series.iloc[-1])
                    or self._is_missing_number(ema20_series.iloc[-2])
                    else self._ema_trend_matches(
                        float(ema20_series.iloc[-1]),
                        float(ema20_series.iloc[-2]),
                    )
                ),
                self.price_position_key: (
                    None
                    if self._is_missing_number(close_series.iloc[-1])
                    or self._is_missing_number(ema20_series.iloc[-1])
                    else self._close_position_matches(
                        float(close_series.iloc[-1]),
                        float(ema20_series.iloc[-1]),
                    )
                ),
                "state_bootstrapped": bootstrapped,
                "creating_order": result,
            }
            self._emit_debug_state(symbol, logging_json)
        except Exception as exc:
            self._logger.error(
                "Cannot run %s strategy for %s, check indicators.log: %s",
                self.strategy_display_name,
                symbol,
                exc,
                exc_info=True,
            )
            return False
        return result
