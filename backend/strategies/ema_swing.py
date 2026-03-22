"""EMA swing strategy."""

from typing import Any

import helper
import model
import talib
from service.database import run_sqlite_write_with_retry
from service.indicators import Indicators
from tortoise.exceptions import BaseORMException, ConfigurationError

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "ema_swing")


class Strategy:
    """EMA swing strategy implementation.

    The strategy requires two consecutive EMA-low swing-up events and only
    returns True when the latest swing low is higher than the previous one.
    """

    def __init__(self, timeframe: str, btc_pulse: Any | None = None):
        self.timeframe = timeframe
        self.indicators = Indicators()
        self._last_log_by_symbol: dict[str, dict[str, Any]] = {}
        self._previous_swing_low_by_symbol: dict[str, float] = {}

    @staticmethod
    def _is_missing_number(value: Any) -> bool:
        """Return True when a numeric value is missing or NaN."""
        return value is None or value != value

    @classmethod
    def _evaluate_swing_candidate(
        cls,
        *,
        close_now: Any,
        close_prev: Any,
        close_prev2: Any,
        ema20: Any,
        ema50: Any,
        ema100: Any,
        ema200: Any,
    ) -> tuple[bool, bool, float | None]:
        """Return trend/swing flags plus the candidate swing low."""
        raw_values = (
            close_now,
            close_prev,
            close_prev2,
            ema20,
            ema50,
            ema100,
            ema200,
        )
        if any(cls._is_missing_number(value) for value in raw_values):
            return False, False, None

        close_now_value = float(close_now)
        close_prev_value = float(close_prev)
        close_prev2_value = float(close_prev2)
        ema20_value = float(ema20)
        ema50_value = float(ema50)
        ema100_value = float(ema100)
        ema200_value = float(ema200)

        trend_ok = (
            ema20_value < ema200_value
            and ema50_value < ema200_value
            and ema100_value < ema200_value
        )
        swing_up = close_now_value > ema20_value and close_prev_value < ema20_value
        swing_low = min(close_prev_value, close_prev2_value)
        return trend_ok, swing_up, swing_low

    @classmethod
    def _find_latest_qualified_swing_low_from_series(
        cls,
        close_series: Any,
        ema20_series: Any,
        ema50_series: Any,
        ema100_series: Any,
        ema200_series: Any,
    ) -> float | None:
        """Return the latest qualified swing low visible in the provided history."""
        latest_swing_low: float | None = None
        for idx in range(2, len(close_series)):
            trend_ok, swing_up, swing_low = cls._evaluate_swing_candidate(
                close_now=close_series.iloc[idx],
                close_prev=close_series.iloc[idx - 1],
                close_prev2=close_series.iloc[idx - 2],
                ema20=ema20_series.iloc[idx],
                ema50=ema50_series.iloc[idx],
                ema100=ema100_series.iloc[idx],
                ema200=ema200_series.iloc[idx],
            )
            if trend_ok and swing_up and swing_low is not None:
                latest_swing_low = swing_low
        return latest_swing_low

    def _bootstrap_previous_swing_low_from_history(
        self, close_series: Any
    ) -> float | None:
        """Reconstruct the latest qualified swing low from stored candle history."""
        ema20_series = talib.EMA(close_series, timeperiod=20)
        ema50_series = talib.EMA(close_series, timeperiod=50)
        ema100_series = talib.EMA(close_series, timeperiod=100)
        ema200_series = talib.EMA(close_series, timeperiod=200)
        return self._find_latest_qualified_swing_low_from_series(
            close_series,
            ema20_series,
            ema50_series,
            ema100_series,
            ema200_series,
        )

    async def _load_persisted_swing_low(self, symbol: str) -> float | None:
        """Load the last qualified swing low from persistent storage."""
        try:
            row = await model.EmaSwingState.get_or_none(
                symbol=symbol,
                timeframe=self.timeframe,
            )
        except (
            BaseORMException,
            ConfigurationError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logging.error(
                "Cannot load persisted EMA swing state for %s on %s: %s",
                symbol,
                self.timeframe,
                exc,
                exc_info=True,
            )
            return None

        if row is None:
            return None
        return float(row.previous_swing_low)

    async def _persist_previous_swing_low(self, symbol: str, swing_low: float) -> None:
        """Persist the latest qualified swing low for restart-safe recovery."""

        async def _persist() -> None:
            await model.EmaSwingState.update_or_create(
                defaults={"previous_swing_low": swing_low},
                symbol=symbol,
                timeframe=self.timeframe,
            )

        try:
            await run_sqlite_write_with_retry(
                _persist,
                f"persisting ema swing state for {symbol} on {self.timeframe}",
            )
        except (
            BaseORMException,
            ConfigurationError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logging.error(
                "Cannot persist EMA swing state for %s on %s: %s",
                symbol,
                self.timeframe,
                exc,
                exc_info=True,
            )

    async def _remember_previous_swing_low(self, symbol: str, swing_low: float) -> None:
        """Update process-local and persisted restart state."""
        self._previous_swing_low_by_symbol[symbol] = swing_low
        await self._persist_previous_swing_low(symbol, swing_low)

    async def _resolve_previous_swing_low(
        self,
        symbol: str,
        close_series: Any,
    ) -> tuple[float | None, bool]:
        """Return the prior qualified swing low and whether it was bootstrapped."""
        if symbol in self._previous_swing_low_by_symbol:
            return self._previous_swing_low_by_symbol[symbol], False

        persisted_swing_low = await self._load_persisted_swing_low(symbol)
        if persisted_swing_low is not None:
            self._previous_swing_low_by_symbol[symbol] = persisted_swing_low
            return persisted_swing_low, False

        bootstrapped_swing_low = self._bootstrap_previous_swing_low_from_history(
            close_series
        )
        if bootstrapped_swing_low is None:
            return None, False

        await self._remember_previous_swing_low(symbol, bootstrapped_swing_low)
        return bootstrapped_swing_low, True

    async def run(self, symbol: str, type: str) -> bool:
        """Evaluate EMA swing-up progression for a symbol."""
        result = False
        ema = await self.indicators.calculate_ema(
            symbol, self.timeframe, [20, 50, 100, 200]
        )
        close = await self.indicators.get_close_price(symbol, self.timeframe, 8)

        try:
            required_emas = ("ema_20", "ema_50", "ema_100", "ema_200")
            if any(ema.get(key) is None for key in required_emas):
                return False
            if close is None:
                return False
            close_series = close.dropna()
            if len(close_series) < 4:
                return False

            trend_ok, swing_up, current_swing_low = self._evaluate_swing_candidate(
                close_now=close_series.iloc[-1],
                close_prev=close_series.iloc[-2],
                close_prev2=close_series.iloc[-3],
                ema20=ema["ema_20"],
                ema50=ema["ema_50"],
                ema100=ema["ema_100"],
                ema200=ema["ema_200"],
            )
            previous_swing_low, bootstrapped = await self._resolve_previous_swing_low(
                symbol,
                close_series,
            )

            if trend_ok and swing_up and current_swing_low is not None:
                if previous_swing_low is not None and not bootstrapped:
                    result = current_swing_low > previous_swing_low
                if previous_swing_low != current_swing_low:
                    await self._remember_previous_swing_low(
                        symbol,
                        current_swing_low,
                    )

            logging_json = {
                "symbol": symbol,
                "ema(20/50/100/200)": (
                    f"{ema['ema_20']}, {ema['ema_50']}, "
                    f"{ema['ema_100']}, {ema['ema_200']}"
                ),
                "close price(last)": f"{close_series.iloc[-1]}",
                "swing_low(current)": current_swing_low,
                "swing_low(previous)": previous_swing_low,
                "state_bootstrapped": bootstrapped,
                "creating_order": result,
            }
            if self._last_log_by_symbol.get(symbol) != logging_json:
                logging.debug("%s", logging_json)
                self._last_log_by_symbol[symbol] = logging_json.copy()
        except Exception as e:
            logging.error(
                "Cannot run strategy for %s, check indicators.log: %s",
                symbol,
                e,
                exc_info=True,
            )
            return False
        return result
