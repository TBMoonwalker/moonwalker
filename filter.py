import requests
from cachetools import cached, TTLCache


class Filter:
    def __init__(self, ws_url, btc_pulse=None):
        self.ws_url = ws_url
        self.btc_pulse = btc_pulse

    def ema(self, symbol, timeframe, length):
        ema_response = requests.get(
            f"{self.ws_url}/indicators/ema/{symbol}/{timeframe}/{length}"
        )

        return ema_response

    @cached(cache=TTLCache(maxsize=1024, ttl=60))
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

    @cached(cache=TTLCache(maxsize=1024, ttl=60))
    def get_rsi(self, symbol, timeframe):
        rsi_response = requests.get(
            f"{self.ws_url}/indicators/rsi/{symbol}/{timeframe}"
        )

        return rsi_response

    def is_on_allowed_list(self, symbol, allow_list):
        result = False
        if allow_list:
            if symbol in allow_list:
                result = True
        else:
            result = True

        return result

    def is_on_deny_list(self, symbol, deny_list):
        result = False
        if deny_list:
            if symbol in deny_list:
                result = True

        return result

    def is_within_topcoin_limit(self, market_cap_rank, topcoin_limit):
        result = False
        if topcoin_limit:
            if market_cap_rank:
                if market_cap_rank <= topcoin_limit:
                    result = True
        else:
            result = True

        return result

    def is_within_rsi_limit(self, rsi_value, rsi_limit_max):
        result = False
        if rsi_limit_max:
            if rsi_value:
                if rsi_value <= rsi_limit_max:
                    result = True
        else:
            result = True

        return result

    def has_enough_volume(self, range, size, volume):
        result = False
        if volume:
            if size and range:
                if float(size) >= float(volume["size"]) and range == volume["range"]:
                    result = True
        else:
            result = True

        return result

    @cached(cache=TTLCache(maxsize=1024, ttl=300))
    def btc_pulse_status(self, timeframe, timeframe_uptrend=None):
        response = True
        btc_pulse = requests.get(
            f"{self.ws_url}/indicators/btc_pulse/{timeframe}"
        ).json()
        if btc_pulse["status"] == "downtrend":
            response = False
        elif btc_pulse["status"] == "uptrend":
            if timeframe_uptrend:
                btc_pulse_uptrend = requests.get(
                    f"{self.ws_url}/indicators/btc_pulse/{timeframe_uptrend}"
                ).json()
                if btc_pulse_uptrend["status"] == "downtrend":
                    response = False
                elif btc_pulse_uptrend["status"] == "uptrend":
                    response = True
            else:
                response = True
        return response

    @cached(cache=TTLCache(maxsize=1024, ttl=86400))
    def get_cmc_marketcap_rank(self, api_key, symbol):
        marketcap = None
        headers = {"X-CMC_PRO_API_KEY": api_key}
        ws_endpoint = "pro-api.coinmarketcap.com"
        ws_context = "v1/cryptocurrency/map"
        start = 1
        limit = 5000
        sort = "cmc_rank"
        url = f"https://{ws_endpoint}/{ws_context}?start={start}&limit={limit}&sort={sort}"
        response = requests.get(
            url,
            headers=headers,
        )

        json_data = response.json()

        if json_data["status"]["error_code"] == 0:
            for entry in json_data["data"]:
                if entry["symbol"] == symbol:
                    marketcap = entry["rank"]

        return marketcap

    def subscribe_new_symbols(self, running_symbols, new_symbol):
        # Automatically subscribe/unsubscribe symbols in Moonloader to reduce load

        # Subscribed symbols
        subscribed_symbols = list(map(str.upper, self.__get_symbol_subscription()))

        # Unsubscribe old symbols
        temp_symbols = list(set(subscribed_symbols) - set(running_symbols))
        unsubscribe_symbols = list(set(temp_symbols) - set(new_symbol))
        for symbol in unsubscribe_symbols:
            requests.get(f"{self.ws_url}/streams/remove/{symbol}")

        # Subscribe new symbols
        temp2_symbols = list(set(running_symbols) - set(subscribed_symbols))
        subscribe_symbols = list(set(new_symbol) - set(temp_symbols))
        if temp2_symbols:
            subscribe_symbols = subscribe_symbols + temp2_symbols

        for symbol in subscribe_symbols:
            requests.get(f"{self.ws_url}/streams/add/{symbol}")

        return (subscribed_symbols, unsubscribe_symbols)

    def __get_symbol_subscription(self):
        subscribed_list = requests.get(f"{self.ws_url}/status/symbols").json()["result"]
        subscribed_symbols = [
            f"{symbol}"
            for symbol, kline in [item.split("@") for item in subscribed_list]
        ]

        if self.btc_pulse:
            for symbol in subscribed_symbols:
                if "btcusdt" in symbol:
                    subscribed_symbols.remove(symbol)
                    break

        return subscribed_symbols
