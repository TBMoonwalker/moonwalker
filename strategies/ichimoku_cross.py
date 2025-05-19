import helper
from service.filter import Filter
from service.indicators import Indicators

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "ichimoku_cross")


class Strategy:
    def __init__(self, timeframe, btc_pulse=None):
        self.timeframe = timeframe
        self.filter = Filter()
        self.indicators = Indicators()

    async def run(self, symbol):
        result = False

        try:
            ichimoku_cross = await self.indicators.calculate_ichimoku_cross(
                symbol, self.timeframe
            )

            if ichimoku_cross == "up":
                # create SO
                result = True

            logging_json = {
                "symbol": symbol,
                "ichimoku_cross": ichimoku_cross,
                "creating_order": result,
            }
            logging.debug(f"{logging_json}")

        except ValueError as e:
            logging.error(f"JSON Message is garbage: {e}")

        return result
