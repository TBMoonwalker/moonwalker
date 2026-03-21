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
        self._last_log_by_symbol: dict[str, dict[str, Any]] = {}

    async def run(self, symbol: str, type: str) -> bool:
        """Evaluate EMA downtrend conditions for a symbol."""
        result = False

        # EMA 20 < EMA 50
        # Close Price -2 > Close Price -3
        ema = await self.indicators.calculate_ema(
            symbol, self.timeframe, [20, 50, 100, 200]
        )
        try:
            if ema.get("ema_20") is None or ema.get("ema_50") is None:
                return False

            if ema["ema_20"] < ema["ema_50"]:
                logging.debug("EMA down for %s", symbol)
                result = True

            logging_json = {
                "symbol": symbol,
                "ema(20/50/100/200)": f"{ema['ema_20']}, {ema['ema_50']}",
                "creating_order": result,
            }
            if self._last_log_by_symbol.get(symbol) != logging_json:
                logging.debug("%s", logging_json)
                self._last_log_by_symbol[symbol] = logging_json.copy()
        except Exception as exc:
            logging.error(
                "Cannot run strategy for %s: %s",
                symbol,
                exc,
                exc_info=True,
            )
            return False
        return result
