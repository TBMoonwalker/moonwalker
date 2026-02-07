"""EMA cross strategy."""

from typing import Any

import helper
from service.filter import Filter
from service.indicators import Indicators

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "ema_cross")


class Strategy:
    """EMA cross strategy implementation."""

    def __init__(self, timeframe: str, btc_pulse: Any | None = None):
        self.timeframe = timeframe
        self.filter = Filter()
        self.indicators = Indicators()

    async def run(self, symbol: str, type: str) -> bool:
        """Evaluate EMA cross conditions for a symbol."""
        result = False

        try:
            ema_cross = await self.indicators.calculate_ema_cross(
                symbol, self.timeframe
            )

            if ema_cross == "up":
                # create SO
                result = True

            logging_json = {
                "symbol": symbol,
                "ema_cross": ema_cross,
                "creating_order": result,
            }
            logging.debug(f"{logging_json}")

        except ValueError as e:
            logging.error(f"JSON Message is garbage: {e}")

        return result
