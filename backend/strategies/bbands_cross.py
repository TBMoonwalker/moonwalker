"""Bollinger Bands cross strategy."""

from typing import Any

import helper
from service.filter import Filter
from service.indicators import Indicators

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "bbands")


class Strategy:
    """BBands cross strategy implementation."""

    def __init__(self, timeframe: str, btc_pulse: Any | None = None):
        self.timeframe = timeframe
        self.filter = Filter()
        self.indicators = Indicators()
        self._last_log_by_symbol: dict[str, dict[str, Any]] = {}

    async def run(self, symbol: str, type: str) -> bool:
        """Evaluate BBands cross conditions for a symbol."""
        result = False

        try:
            bbands = await self.indicators.calculate_bbands_cross(
                symbol, self.timeframe, 50
            )

            if bbands != "none":
                # create SO
                result = True

            logging_json = {
                "symbol": symbol,
                "bbands": bbands,
                "creating_order": result,
            }
            if self._last_log_by_symbol.get(symbol) != logging_json:
                logging.debug(f"{logging_json}")
                self._last_log_by_symbol[symbol] = logging_json.copy()

        except ValueError as e:
            logging.error(f"JSON Message is garbage: {e}")

        return result
