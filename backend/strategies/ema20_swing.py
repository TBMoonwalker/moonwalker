"""EMA20 swing strategy."""

from typing import Any

import helper
import model
import talib
from service.database import run_sqlite_write_with_retry
from service.indicators import Indicators
from tortoise.exceptions import BaseORMException, ConfigurationError

logging = helper.LoggerFactory.get_logger(
    "logs/strategies.log",
    "ema20_swing",
)

EMA20_LOOKBACK_LENGTH = 50
EMA20_STATE_VERSION_SUFFIX = ":v2"


class Strategy:
    """EMA20 swing strategy implementation.

    The strategy only evaluates EMA20. It returns True when the latest closed
    candle sits above its EMA20 and that closed candle's EMA20 value is higher
    than the previous candle's EMA20 value.

    To avoid re-triggering the same qualifying candle after repeated runtime
    evaluations or a process restart, the strategy remembers the last emitted
    qualifying closed-candle state per symbol/timeframe.
    """

    def __init__(self, timeframe: str, btc_pulse: Any | None = None):
        del btc_pulse
        self.timeframe = timeframe
        self._state_timeframe = f"{timeframe}{EMA20_STATE_VERSION_SUFFIX}"
        self.indicators = Indicators()
        self._last_log_by_symbol: dict[str, dict[str, Any]] = {}
        self._previous_state_by_symbol: dict[str, tuple[float, float]] = {}

    def _emit_debug_state(self, symbol: str, payload: dict[str, Any]) -> None:
        """Write one structured debug line per symbol state change."""
        if self._last_log_by_symbol.get(symbol) == payload:
            return
        logging.debug("%s", payload)
        self._last_log_by_symbol[symbol] = payload.copy()

    @staticmethod
    def _is_missing_number(value: Any) -> bool:
        """Return True when a numeric value is missing or NaN."""
        return value is None or value != value

    @classmethod
    def _evaluate_trigger_candidate(
        cls,
        *,
        close_value: Any,
        ema20_value: Any,
        previous_ema20_value: Any,
    ) -> tuple[bool, float | None, float | None]:
        """Return the bullish trigger flag plus the candidate closed-candle state."""
        raw_values = (close_value, ema20_value, previous_ema20_value)
        if any(cls._is_missing_number(value) for value in raw_values):
            return False, None, None

        close_value_float = float(close_value)
        ema20_value_float = float(ema20_value)
        previous_ema20_value_float = float(previous_ema20_value)

        trigger_up = (
            ema20_value_float > previous_ema20_value_float
            and close_value_float > ema20_value_float
        )
        return trigger_up, close_value_float, ema20_value_float

    @classmethod
    def _find_latest_qualified_state_from_series(
        cls,
        close_series: Any,
        ema20_series: Any,
    ) -> tuple[float, float] | None:
        """Return the latest qualifying closed-candle state from history."""
        latest_state: tuple[float, float] | None = None
        for idx in range(1, len(close_series) - 1):
            trigger_up, close_value, ema20_value = cls._evaluate_trigger_candidate(
                close_value=close_series.iloc[idx],
                ema20_value=ema20_series.iloc[idx],
                previous_ema20_value=ema20_series.iloc[idx - 1],
            )
            if trigger_up and close_value is not None and ema20_value is not None:
                latest_state = (close_value, ema20_value)
        return latest_state

    @staticmethod
    def _build_ema20_series(close_series: Any) -> Any:
        """Build the EMA20 series from the provided close history."""
        return talib.EMA(close_series, timeperiod=20)

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
            row = await model.Ema20SwingState.get_or_none(
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
            logging.error(
                "Cannot load persisted EMA20 swing state for %s on %s: %s",
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
            await model.Ema20SwingState.update_or_create(
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
                f"persisting ema20 swing state for {symbol} on {self.timeframe}",
            )
        except (
            BaseORMException,
            ConfigurationError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logging.error(
                "Cannot persist EMA20 swing state for %s on %s: %s",
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
        """Evaluate EMA20 bullish progression for a symbol."""
        del type
        result = False
        ema = await self.indicators.calculate_ema(symbol, self.timeframe, [20])
        close = await self.indicators.get_close_price(
            symbol,
            self.timeframe,
            EMA20_LOOKBACK_LENGTH,
        )

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
            if len(close_series) < 22:
                self._emit_debug_state(
                    symbol,
                    {
                        "symbol": symbol,
                        "reason": "insufficient_closed_candles",
                        "ema20(current)": ema.get("ema_20"),
                        "available_closed_candles": int(len(close_series)),
                        "required_closed_candles": 22,
                        "creating_order": False,
                    },
                )
                return False

            ema20_series = self._build_ema20_series(close_series)
            trigger_up, current_close_value, current_ema20 = (
                self._evaluate_trigger_candidate(
                    close_value=close_series.iloc[-2],
                    ema20_value=ema20_series.iloc[-2],
                    previous_ema20_value=ema20_series.iloc[-3],
                )
            )
            previous_state, bootstrapped = await self._resolve_previous_state(
                symbol,
                close_series,
            )
            previous_close_value = previous_state[0] if previous_state else None
            previous_ema20 = previous_state[1] if previous_state else None

            if (
                trigger_up
                and current_close_value is not None
                and current_ema20 is not None
            ):
                if (
                    previous_state is not None
                    and not bootstrapped
                    and previous_close_value is not None
                    and previous_ema20 is not None
                ):
                    result = (
                        current_close_value != previous_close_value
                        or current_ema20 != previous_ema20
                    )
                if previous_state != (current_close_value, current_ema20):
                    await self._remember_previous_state(
                        symbol,
                        current_close_value,
                        current_ema20,
                    )

            logging_json = {
                "symbol": symbol,
                "close(closed/current)": (
                    f"{close_series.iloc[-2]} / {close_series.iloc[-1]}"
                ),
                "ema20(closed/current)": f"{ema20_series.iloc[-2]} / {ema['ema_20']}",
                "ema20(previous_closed)": ema20_series.iloc[-3],
                "trigger_close(current)": (current_close_value if trigger_up else None),
                "trigger_close(previous)": previous_close_value,
                "ema20(closed)": current_ema20,
                "ema20(previous_trigger)": previous_ema20,
                "ema20_rising": (
                    None
                    if self._is_missing_number(ema20_series.iloc[-2])
                    or self._is_missing_number(ema20_series.iloc[-3])
                    else float(ema20_series.iloc[-2]) > float(ema20_series.iloc[-3])
                ),
                "closed_above_ema20": (
                    None
                    if self._is_missing_number(close_series.iloc[-2])
                    or self._is_missing_number(ema20_series.iloc[-2])
                    else float(close_series.iloc[-2]) > float(ema20_series.iloc[-2])
                ),
                "state_bootstrapped": bootstrapped,
                "creating_order": result,
            }
            self._emit_debug_state(symbol, logging_json)
        except Exception as exc:
            logging.error(
                "Cannot run EMA20 swing strategy for %s, check indicators.log: %s",
                symbol,
                exc,
                exc_info=True,
            )
            return False
        return result
