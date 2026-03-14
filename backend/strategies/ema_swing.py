"""EMA swing strategy."""

from typing import Any

import helper
from service.indicators import Indicators

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

            trend_ok = (
                ema["ema_20"] < ema["ema_200"]
                and ema["ema_50"] < ema["ema_200"]
                and ema["ema_100"] < ema["ema_200"]
            )

            swing_up = (
                close_series.iloc[-1] > ema["ema_20"]
                and close_series.iloc[-2] < ema["ema_20"]
            )

            current_swing_low = min(
                float(close_series.iloc[-2]), float(close_series.iloc[-3])
            )
            previous_swing_low = self._previous_swing_low_by_symbol.get(symbol)

            if trend_ok and swing_up and previous_swing_low is not None:
                result = current_swing_low > previous_swing_low

            if trend_ok and swing_up:
                self._previous_swing_low_by_symbol[symbol] = current_swing_low

            logging_json = {
                "symbol": symbol,
                "ema(20/50/100/200)": (
                    f"{ema['ema_20']}, {ema['ema_50']}, "
                    f"{ema['ema_100']}, {ema['ema_200']}"
                ),
                "close price(last)": f"{close_series.iloc[-1]}",
                "swing_low(current)": current_swing_low,
                "swing_low(previous)": previous_swing_low,
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
            )
            return False
        return result
