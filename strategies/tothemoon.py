import requests
from logger import LoggerFactory
from filter import Filter


class Strategy:
    def __init__(self, ws_url, loglevel):
        self.ws_url = ws_url

        self.logging = LoggerFactory.get_logger(
            "strategies.log", "tothemoon", log_level=loglevel
        )
        self.filter = Filter(ws_url=ws_url)
        self.logging.info("Initialized")

    def run(self, symbol, price):
        try:
            sma_slope_15m = self.filter.sma_slope(symbol, "15Min").json()
            sma_15m = self.filter.sma(symbol, "15Min").json()

            self.logging.debug(f"SMA slope: {sma_slope_15m}")
            self.logging.debug(f"SMA: {sma_15m}")
            if sma_slope_15m["status"] == "upward" and sma_15m["status"] < price:
                # create SO
                result = True
            else:
                # avoid SO
                result = False
        except ValueError as e:
            self.logging.error(f"JSON Message is garbage: {e}")

        return result
