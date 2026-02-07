"""EMA downtrend strategy."""

from typing import Any

import helper
from service.filter import Filter
from service.indicators import Indicators

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "ema_down")


class Strategy:
    """EMA downtrend strategy implementation."""

    def __init__(self, timeframe: str, btc_pulse: Any | None = None):
        self.timeframe = timeframe
        self.filter = Filter()
        self.indicators = Indicators()

    async def run(self, symbol: str, type: str) -> bool:
        """Evaluate EMA downtrend conditions for a symbol."""
        result = False

        # EMA 20 < EMA 50
        # Close Price -2 > Close Price -3
        ema = await self.indicators.calculate_ema(
            symbol, self.timeframe, [20, 50, 100, 200]
        )
        try:
            if ema["ema_20"] < ema["ema_50"]:
                logging.debug(f"EMA down for {symbol}")
                result = True

            logging_json = {
                "symbol": symbol,
                "ema(20/50/100/200)": f"{ema['ema_20']}, {ema['ema_50']}",
                "creating_order": result,
            }
            logging.debug(f"{logging_json}")
        except Exception as exc:
            logging.error(f"Cannot run strategy for {symbol}: {exc}", exc_info=True)
            return False
        return result
