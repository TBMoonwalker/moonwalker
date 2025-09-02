import helper
from service.filter import Filter
from service.indicators import Indicators

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "ema_low")


class Strategy:
    def __init__(self, timeframe, btc_pulse=None):
        self.timeframe = timeframe
        self.filter = Filter()
        self.indicators = Indicators()

    async def run(self, symbol):
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
            if (
                ema["ema_20"] < ema["ema_200"]
                and ema["ema_50"] < ema["ema_200"]
                and ema["ema_100"] < ema["ema_200"]
            ):
                # Check if rebound happened
                if (
                    close.dropna().iloc[-2] > ema["ema_20"]
                    and close.dropna().iloc[-3] < ema["ema_20"]
                ):
                    logging.debug(
                        f"Price rebound from EMA down for {symbol} Close: {close.dropna().iloc[-2]} Previous close: {close.dropna().iloc[-3]}"
                    )
                    result = True

            logging_json = {
                "symbol": symbol,
                "ema(20/50/100/200)": f"{ema["ema_20"]}, {ema["ema_50"]}, {ema["ema_100"]}, {ema["ema_200"]}",
                "close price(last)": f"{close.dropna().iloc[-2]}",
                "creating_order": result,
            }
            logging.debug(f"{logging_json}")
        except:
            logging.error("Cannot run strategy, check indicators.log")
            return False
        return result
