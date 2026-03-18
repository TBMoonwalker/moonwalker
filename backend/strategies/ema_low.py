"""EMA low strategy."""

from typing import Any

import helper
from service.indicators import Indicators

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "ema_low")


class Strategy:
    """EMA low strategy implementation."""

    def __init__(self, timeframe: str, btc_pulse: Any | None = None):
        self.timeframe = timeframe
        self.indicators = Indicators()
        self._last_log_by_symbol: dict[str, dict[str, Any]] = {}

    async def run(self, symbol: str, type: str) -> bool:
        """Evaluate EMA low conditions for a symbol.

        Strategy summary:
        - Trend filter: EMA20, EMA50, and EMA100 must all be below EMA200
          (downtrend / "low" regime).
        - Entry trigger: price rebounds above EMA20 after being below it
          (close[-1] > EMA20 and close[-2] < EMA20).
        The method returns True when both conditions are met.
        """
        result = False

        # EMA 20 < EMA 200
        # EMA 50 < EMA 200
        # EMA 100 < EMA 200
        # Close Price -2 > Close Price -3
        ema = await self.indicators.calculate_ema(
            symbol, self.timeframe, [20, 50, 100, 200]
        )
        close = await self.indicators.get_close_price(symbol, self.timeframe, 5)
        try:
            required_emas = ("ema_20", "ema_50", "ema_100", "ema_200")
            if any(ema.get(key) is None for key in required_emas):
                return False

            if close is None:
                return False
            close_series = close.dropna()
            if len(close_series) < 3:
                return False

            if (
                ema["ema_20"] < ema["ema_200"]
                and ema["ema_50"] < ema["ema_200"]
                and ema["ema_100"] < ema["ema_200"]
            ):
                # Check if rebound happened
                if (
                    close_series.iloc[-2] > ema["ema_20"]
                    and close_series.iloc[-3] < ema["ema_20"]
                ):
                    result = True

            logging_json = {
                "symbol": symbol,
                "ema(20/50/100/200)": f"{ema['ema_20']}, {ema['ema_50']}, {ema['ema_100']}, {ema['ema_200']}",
                "close price(last)": f"{close_series.iloc[-1]}",
                "creating_order": result,
            }
            if self._last_log_by_symbol.get(symbol) != logging_json:
                logging.debug(f"{logging_json}")
                self._last_log_by_symbol[symbol] = logging_json.copy()
        except Exception as e:
            logging.error(
                f"Cannot run strategy for {symbol}, check indicators.log: {e}"
            )
            return False
        return result
