import helper
from service.filter import Filter
from service.indicators import Indicators

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "ema_down")


class Strategy:
    def __init__(self, timeframe, btc_pulse=None):
        self.timeframe = timeframe
        self.filter = Filter()
        self.indicators = Indicators()

    async def run(self, symbol, type):
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
        except:
            logging.error("Cannot run strategy, check indicators.log")
            return False
        return result
