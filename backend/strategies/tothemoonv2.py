"""ToTheMoon strategy."""

import helper
from service.filter import Filter
from service.indicators import Indicators

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "tothemoonv2")


class Strategy:
    """ToTheMoon strategy implementation."""

    def __init__(self, timeframe: str):
        self.timeframe = timeframe
        self.filter = Filter()
        self.indicators = Indicators()
        self._last_log_by_symbol: dict[str, dict[str, object]] = {}

    async def run(self, symbol: str, type: str) -> bool:
        """Evaluate ToTheMoon conditions for a symbol."""
        result = False

        try:
            ema_slope_50 = await self.indicators.calculate_ema_slope(
                symbol, self.timeframe, 50
            )
            ema_slope_9 = await self.indicators.calculate_ema_slope(
                symbol, self.timeframe, 9
            )
            rsi_slope_14 = await self.indicators.calculate_rsi_slope(
                symbol, self.timeframe, 14
            )
            ema_cross = await self.indicators.calculate_ema_cross(
                symbol, self.timeframe
            )

            if (
                ema_slope_9 == "upward"
                and ema_slope_50 == "upward"
                and rsi_slope_14 == "upward"
            ) or ema_cross == "up":
                # create SO
                result = True

            logging_json = {
                "symbol": symbol,
                "ema_slope_9": ema_slope_9,
                "ema_slope_50": ema_slope_50,
                "rsi_slope_14": rsi_slope_14,
                "ema_cross": ema_cross,
                "creating_order": result,
            }
            if self._last_log_by_symbol.get(symbol) != logging_json:
                logging.debug("%s", logging_json)
                self._last_log_by_symbol[symbol] = logging_json.copy()

        except ValueError as e:
            logging.error("JSON Message is garbage: %s", e)

        return result
