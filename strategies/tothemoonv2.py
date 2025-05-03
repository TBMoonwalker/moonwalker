import helper
from service.filter import Filter
from service.indicators import Indicators

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "tothemoonv2")


class Strategy:
    def __init__(self, btc_pulse, timeframe):
        self.btc_pulse = btc_pulse
        self.timeframe = timeframe
        self.filter = Filter()
        self.indicators = Indicators()
        logging.info("Initialized")

    async def run(self, symbol, price):
        result = False

        try:
            btc_pulse = True
            if self.btc_pulse:
                btc_pulse = self.filter.btc_pulse_status("5Min", "10Min")

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

            if btc_pulse:
                # rsi = self.filter.get_rsi(symbol, self.timeframe).json()
                # rsi_value = float(rsi["status"])
                # support_level_30m = self.filter.support_level(symbol, "1d", 10).json()
                # support_level = support_level_30m["status"]

                # TODO: Implement extreme wick detection (high percentage down in one candle)
                # logging.debug(f"Support Level: {support_level}")
                # logging.debug(f"RSI value: {rsi_value}")

                # if rsi_value <= 30:
                if (
                    ema_slope_9 == "upward"
                    and ema_slope_50 == "upward"
                    and rsi_slope_14 == "upward"
                    and ema_cross == "up"
                ):
                    # create SO
                    result = True
            else:
                logging.info(
                    "BTC-Pulse is in downtrend - not creating new safety orders"
                )

            logging_json = {
                "symbol": symbol,
                "ema_slope_9": ema_slope_9,
                "ema_slope_50": ema_slope_50,
                "rsi_slope_14": rsi_slope_14,
                "ema_cross": ema_cross,
                "creating_so": result,
            }
            logging.debug(f"{logging_json}")

            return result

        except ValueError as e:
            logging.error(f"JSON Message is garbage: {e}")
