import helper
from service.filter import Filter
from service.indicators import Indicators

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "ema_cross")


class Strategy:
    def __init__(self, timeframe, btc_pulse=None):
        self.timeframe = timeframe
        self.filter = Filter()
        self.indicators = Indicators()

    async def run(self, symbol):
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
