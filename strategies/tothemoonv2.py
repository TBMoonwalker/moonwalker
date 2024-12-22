import requests
from logger import LoggerFactory
from filter import Filter


class Strategy:
    def __init__(self, ws_url, loglevel, btc_pulse):
        self.ws_url = ws_url
        self.btc_pulse = btc_pulse

        Strategy.logging = LoggerFactory.get_logger(
            "logs/strategies.log", "tothemoon", log_level=loglevel
        )
        self.filter = Filter(ws_url=ws_url, loglevel=loglevel)
        Strategy.logging.info("Initialized")

    def run(self, symbol, price):
        result = False

        try:
            btc_pulse = True
            if self.btc_pulse:
                btc_pulse = self.filter.btc_pulse_status("5Min", "10Min")

            if btc_pulse:
                ema_slope_50 = self.filter.ema_slope(symbol, "15Min", 50).json()
                ema_slope_9 = self.filter.ema_slope(symbol, "15Min", 9).json()
                ema_cross_15m = self.filter.ema_cross(symbol, "15Min").json()
                # rsi = self.filter.get_rsi(symbol, "15Min").json()
                # rsi_value = float(rsi["status"])
                # support_level_30m = self.filter.support_level(symbol, "1d", 10).json()
                # support_level = support_level_30m["status"]

                Strategy.logging.debug(f"Symbol: {symbol}")
                Strategy.logging.debug(f"EMA slope 9: {ema_slope_9}")
                Strategy.logging.debug(f"EMA slope 50: {ema_slope_50}")
                Strategy.logging.debug(f"EMA cross: {ema_cross_15m}")
                # Strategy.logging.debug(f"Support Level: {support_level}")
                # Strategy.logging.debug(f"RSI value: {rsi_value}")

                # if rsi_value <= 30:
                if (
                    ema_slope_9["status"] == "upward"
                    and ema_slope_50["status"] == "upward"
                ) and ema_cross_15m["status"] == "up":
                    # create SO
                    result = True
            else:
                Strategy.logging.info(
                    "BTC-Pulse is in downtrend - not creating new safety orders"
                )

        except ValueError as e:
            Strategy.logging.error(f"JSON Message is garbage: {e}")

        return result
