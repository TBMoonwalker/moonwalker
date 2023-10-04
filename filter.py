import requests


class Filter:
    def __init__(self, ws_url):
        self.ws_url = ws_url

    def add_symbol_to_stream(self, symbol):
        response = requests.get(f"{self.ws_url}/streams/add/{symbol}")

    def ema_cross(self, symbol, timeframe):
        ema_cross_response = requests.get(
            f"{self.ws_url}/indicators/ema_cross/{symbol}/{timeframe}"
        )

        return ema_cross_response

    def sma_slope(self, symbol, timeframe):
        sma_slope_response = requests.get(
            f"{self.ws_url}/indicators/sma_slope/{symbol}/{timeframe}"
        )

        return sma_slope_response

    def sma(self, symbol, timeframe):
        sma_response = requests.get(
            f"{self.ws_url}/indicators/sma/{symbol}/{timeframe}"
        )

        return sma_response

    def ema(self, symbol, timeframe):
        ema_response = requests.get(
            f"{self.ws_url}/indicators/ema/{symbol}/{timeframe}"
        )

        return ema_response

    def rsi(self, symbol, timeframe):
        rsi_response = requests.get(
            f"{self.ws_url}/indicators/rsi/{symbol}/{timeframe}"
        )

        return rsi_response
