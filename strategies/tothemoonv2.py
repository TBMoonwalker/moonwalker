import requests
from logger import LoggerFactory
from filter import Filter


class Strategy:
    def __init__(self, ws_url, loglevel, btc_pulse, currency, timeframe):
        self.ws_url = ws_url
        self.btc_pulse = btc_pulse
        self.timeframe = timeframe

        self.logging = LoggerFactory.get_logger(
            "logs/strategies.log", "tothemoonv2", log_level=loglevel
        )
        self.filter = Filter(ws_url=ws_url, loglevel=loglevel, currency=currency)
        self.logging.info("Initialized")

    def run(self, symbol, price):
        result = False

        try:
            btc_pulse = True
            if self.btc_pulse:
                btc_pulse = self.filter.btc_pulse_status("5Min", "10Min")

            if btc_pulse:
                ema_slope_50 = self.filter.ema_slope(symbol, self.timeframe, 50).json()
                ema_slope_9 = self.filter.ema_slope(symbol, self.timeframe, 9).json()
                rsi_slope_14 = self.filter.rsi_slope(symbol, self.timeframe, 14).json()
                ema_cross = self.filter.ema_cross(symbol, self.timeframe).json()
                # rsi = self.filter.get_rsi(symbol, self.timeframe).json()
                # rsi_value = float(rsi["status"])
                # support_level_30m = self.filter.support_level(symbol, "1d", 10).json()
                # support_level = support_level_30m["status"]

                self.logging.debug(f"Symbol: {symbol}")
                self.logging.debug(f"EMA slope 9: {ema_slope_9}")
                self.logging.debug(f"EMA slope 50: {ema_slope_50}")
                self.logging.debug(f"RSI slope 14: {rsi_slope_14}")
                self.logging.debug(f"EMA cross: {ema_cross}")
                # TODO: Implement extreme wick detection (high percentage down in one candle)
                # self.logging.debug(f"Support Level: {support_level}")
                # self.logging.debug(f"RSI value: {rsi_value}")

                # if rsi_value <= 30:
                if (
                    ema_slope_9["status"] == "upward"
                    and ema_slope_50["status"] == "upward"
                    and rsi_slope_14["status"] == "upward"
                    and ema_cross["status"] == "up"
                ):
                    # create SO
                    result = True
            else:
                self.logging.info(
                    "BTC-Pulse is in downtrend - not creating new safety orders"
                )

        except ValueError as e:
            self.logging.error(f"JSON Message is garbage: {e}")

        self.logging.debug(f"Creating SO: {result}")

        return result
