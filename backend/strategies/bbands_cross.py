import helper
from service.filter import Filter
from service.indicators import Indicators

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "bbands")


class Strategy:
    def __init__(self, timeframe, btc_pulse=None):
        self.timeframe = timeframe
        self.filter = Filter()
        self.indicators = Indicators()

    async def run(self, symbol, type):
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
            logging.debug(f"{logging_json}")

        except ValueError as e:
            logging.error(f"JSON Message is garbage: {e}")

        return result
