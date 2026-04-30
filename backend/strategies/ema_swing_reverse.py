"""EMA swing reverse strategy."""

from typing import Any

import helper
import model
import talib
from service.database import run_sqlite_write_with_retry
from service.indicators import Indicators
from tortoise.exceptions import BaseORMException, ConfigurationError

logging = helper.LoggerFactory.get_logger(
    "logs/strategies.log",
    "ema_swing_reverse",
)

EMA20_LOOKBACK_LENGTH = 50
EMA20_STATE_VERSION_SUFFIX = ":v2"


class Strategy:
    """EMA swing reverse strategy implementation.

    The strategy only evaluates EMA20. It looks for completed EMA20 swings
    where the line turns from rising to falling and returns True when both the
    latest EMA20 value and that swing value are lower than the previously
    recorded EMA20 swing state for the same symbol and timeframe.
    """

    def __init__(self, timeframe: str, btc_pulse: Any | None = None):
        del btc_pulse
        self.timeframe = timeframe
        self._state_timeframe = f"{timeframe}{EMA20_STATE_VERSION_SUFFIX}"
        self.indicators = Indicators()
        self._last_log_by_symbol: dict[str, dict[str, Any]] = {}
        self._previous_state_by_symbol: dict[str, tuple[float, float]] = {}

    @staticmethod
    def _is_missing_number(value: Any) -> bool:
        """Return True when a numeric value is missing or NaN."""
        return value is None or value != value

    @classmethod
    def _evaluate_swing_candidate(
        cls,
        *,
        ema20_now: Any,
        ema20_prev: Any,
        ema20_prev2: Any,
    ) -> tuple[bool, float | None, float | None]:
        """Return the EMA20 down-swing flag plus the candidate swing state."""
        raw_values = (ema20_now, ema20_prev, ema20_prev2)
        if any(cls._is_missing_number(value) for value in raw_values):
            return False, None, None

        ema20_now_value = float(ema20_now)
        ema20_prev_value = float(ema20_prev)
        ema20_prev2_value = float(ema20_prev2)

        swing_down = (
            ema20_prev_value > ema20_prev2_value and ema20_prev_value > ema20_now_value
        )
        return swing_down, ema20_prev_value, ema20_now_value

    @classmethod
    def _find_latest_qualified_swing_state_from_series(
        cls,
        ema20_series: Any,
    ) -> tuple[float, float] | None:
        """Return the latest EMA20 swing state visible in the provided history."""
        latest_state: tuple[float, float] | None = None
        for idx in range(2, len(ema20_series)):
            swing_down, swing_value, ema20_value = cls._evaluate_swing_candidate(
                ema20_now=ema20_series.iloc[idx],
                ema20_prev=ema20_series.iloc[idx - 1],
                ema20_prev2=ema20_series.iloc[idx - 2],
            )
            if swing_down and swing_value is not None and ema20_value is not None:
                latest_state = (swing_value, ema20_value)
        return latest_state

    @staticmethod
    def _build_ema20_series(close_series: Any) -> Any:
        """Build the EMA20 series from the provided close history."""
        return talib.EMA(close_series, timeperiod=20)

    def _bootstrap_previous_state_from_history(
        self,
        close_series: Any,
    ) -> tuple[float, float] | None:
        """Reconstruct the latest EMA20 swing state from stored candle history."""
        ema20_series = self._build_ema20_series(close_series)
        return self._find_latest_qualified_swing_state_from_series(ema20_series)

    async def _load_persisted_state(
        self,
        symbol: str,
    ) -> tuple[float, float] | None:
        """Load the last qualified EMA20 swing state from persistent storage."""
        try:
            row = await model.EmaSwingReverseState.get_or_none(
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
                "Cannot load persisted EMA swing reverse state for %s on %s: %s",
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
        swing_low: float,
        ema20_value: float,
    ) -> None:
        """Persist the latest qualified EMA20 swing state for restart-safe recovery."""

        async def _persist() -> None:
            await model.EmaSwingReverseState.update_or_create(
                defaults={
                    "previous_swing_low": swing_low,
                    "previous_ema20": ema20_value,
                },
                symbol=symbol,
                timeframe=self._state_timeframe,
            )

        try:
            await run_sqlite_write_with_retry(
                _persist,
                (
                    "persisting ema swing reverse state "
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
            logging.error(
                "Cannot persist EMA swing reverse state for %s on %s: %s",
                symbol,
                self.timeframe,
                exc,
                exc_info=True,
            )

    async def _remember_previous_state(
        self,
        symbol: str,
        swing_low: float,
        ema20_value: float,
    ) -> None:
        """Update process-local and persisted restart state."""
        self._previous_state_by_symbol[symbol] = (swing_low, ema20_value)
        await self._persist_previous_state(symbol, swing_low, ema20_value)

    async def _resolve_previous_state(
        self,
        symbol: str,
        close_series: Any,
    ) -> tuple[tuple[float, float] | None, bool]:
        """Return the prior EMA20 swing state and whether it was bootstrapped."""
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
        """Evaluate EMA20 swing reverse progression for a symbol."""
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
                return False
            if close is None:
                return False
            close_series = close.dropna()
            if len(close_series) < 22:
                return False

            ema20_series = self._build_ema20_series(close_series)
            swing_down, current_swing_value, current_ema20 = (
                self._evaluate_swing_candidate(
                    ema20_now=ema20_series.iloc[-1],
                    ema20_prev=ema20_series.iloc[-2],
                    ema20_prev2=ema20_series.iloc[-3],
                )
            )
            previous_state, bootstrapped = await self._resolve_previous_state(
                symbol,
                close_series,
            )
            previous_swing_value = previous_state[0] if previous_state else None
            previous_ema20 = previous_state[1] if previous_state else None

            if (
                swing_down
                and current_swing_value is not None
                and current_ema20 is not None
            ):
                if (
                    previous_state is not None
                    and not bootstrapped
                    and previous_swing_value is not None
                    and previous_ema20 is not None
                ):
                    result = (
                        current_swing_value < previous_swing_value
                        and current_ema20 < previous_ema20
                    )
                if previous_state != (current_swing_value, current_ema20):
                    await self._remember_previous_state(
                        symbol,
                        current_swing_value,
                        current_ema20,
                    )

            logging_json = {
                "symbol": symbol,
                "ema20(series/current)": f"{ema20_series.iloc[-1]} / {ema['ema_20']}",
                "ema20(prev2)": ema20_series.iloc[-3],
                "ema20_swing(current)": current_swing_value,
                "ema20_swing(previous)": previous_swing_value,
                "ema20(current)": current_ema20,
                "ema20(previous)": previous_ema20,
                "swing_down_detected": swing_down,
                "state_bootstrapped": bootstrapped,
                "creating_order": result,
            }
            if self._last_log_by_symbol.get(symbol) != logging_json:
                logging.debug("%s", logging_json)
                self._last_log_by_symbol[symbol] = logging_json.copy()
        except Exception as exc:
            logging.error(
                "Cannot run reverse strategy for %s, check indicators.log: %s",
                symbol,
                exc,
                exc_info=True,
            )
            return False
        return result
