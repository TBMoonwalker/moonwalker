import requests
from logger import LoggerFactory
from filter import Filter


class Strategy:
    def __init__(self, ws_url, loglevel):
        self.ws_url = ws_url

        self.logging = LoggerFactory.get_logger(
            "logs/strategies.log", "tothemoon", log_level=loglevel
        )
        self.filter = Filter(ws_url=ws_url)
        self.logging.info("Initialized")

    def run(self, symbol, price):
        result = False

        try:
            support_level_30m = self.filter.support_level(symbol, "4h", 10).json()
            support_level = support_level_30m["status"]

            self.logging.debug(f"Symbol: {symbol}")
            self.logging.debug(f"Support Level: {support_level}")

            if support_level == "True":
                # create SO
                result = True

        except ValueError as e:
            self.logging.error(f"JSON Message is garbage: {e}")

        return result
