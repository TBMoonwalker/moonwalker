import requests
from cachetools import cached, TTLCache
from logger import LoggerFactory
from tenacity import retry, TryAgain, stop_after_attempt, wait_fixed


class Filter:
    def __init__(self, ws_url, loglevel, btc_pulse=None):
        self.ws_url = ws_url
        self.btc_pulse = btc_pulse

        Filter.logging = LoggerFactory.get_logger(
            "logs/filter.log", "filter", log_level=loglevel
        )
        Filter.logging.info("Initialized")

    @retry(wait=wait_fixed(10), stop=stop_after_attempt(10))
    def __request_api_endpoint(self, request):
        response = None
        try:
            response = requests.get(f"{request}")
        except requests.exceptions.RequestException as e:
            Filter.logging.error(f"Error getting response for {request}. Cause: {e}")
            raise TryAgain

        return response

    @cached(cache=TTLCache(maxsize=1024, ttl=60))
    def sma_slope(self, symbol, timeframe):
        sma_slope_response = self.__request_api_endpoint(
            f"{self.ws_url}/indicators/sma_slope/{symbol}/{timeframe}"
        )

        return sma_slope_response

    @cached(cache=TTLCache(maxsize=1024, ttl=60))
    def get_rsi(self, symbol, timeframe):
        rsi_response = self.__request_api_endpoint(
            f"{self.ws_url}/indicators/rsi/{symbol}/{timeframe}"
        )

        return rsi_response

    @cached(cache=TTLCache(maxsize=1024, ttl=60))
    def ema_cross(self, symbol, timeframe):
        ema_cross_response = self.__request_api_endpoint(
            f"{self.ws_url}/indicators/ema_cross/{symbol}/{timeframe}"
        )

        return ema_cross_response

    @cached(cache=TTLCache(maxsize=1024, ttl=300))
    def support_level(self, symbol, timeframe, num_level):
        support_level_response = self.__request_api_endpoint(
            f"{self.ws_url}/indicators/support/{symbol}/{timeframe}/{num_level}"
        )

        return support_level_response

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

        # Subscribe BTC symbol if not available
        subscribed_symbols = self.__get_symbols()
        if subscribed_symbols:
            for symbol in subscribed_symbols:
                if "BTCUSDT" not in symbol:
                    self.__request_api_endpoint(f"{self.ws_url}/symbol/add/BTC")
                    break
        else:
            self.__request_api_endpoint(f"{self.ws_url}/symbol/add/BTC")

        btc_pulse = self.__request_api_endpoint(
            f"{self.ws_url}/indicators/btc_pulse/{timeframe}"
        ).json()
        if btc_pulse["status"] == "downtrend":
            response = False
        elif btc_pulse["status"] == "uptrend":
            if timeframe_uptrend:
                btc_pulse_uptrend = self.__request_api_endpoint(
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
        response = self.__request_api_endpoint(
            url,
            headers=headers,
        )

        try:
            json_data = response.json()
        except Exception as e:
            print(e)

        if json_data["status"]["error_code"] == 0:
            for entry in json_data["data"]:
                if entry["symbol"] == symbol:
                    marketcap = entry["rank"]

        return marketcap

    def subscribe_new_symbols(self, running_symbols, new_symbol):
        # Automatically subscribe/unsubscribe symbols in Moonloader to reduce load

        # Subscribed symbols (in Moonloader)
        subscribed_symbols = list(map(str.upper, self.__get_symbol_subscription()))
        Filter.logging.debug(f"Subscribed Symbols: {subscribed_symbols}")
        Filter.logging.debug(f"Running Symbols: {subscribed_symbols}")

        # Unsubscribe old symbols
        # Running Symbols = running in Moonwalker
        # Subscribed Symbols = subscribed in Moonloader
        temp_symbols = list(set(subscribed_symbols) - set(running_symbols))
        Filter.logging.debug(f"Diff Subscribed/Running: {temp_symbols}")
        unsubscribe_symbols = list(set(temp_symbols) - set(new_symbol))
        Filter.logging.debug(f"Unsubscribe: {subscribed_symbols}")
        for symbol in unsubscribe_symbols:
            self.__request_api_endpoint(f"{self.ws_url}/symbol/remove/{symbol}")

        # Subscribe new symbols
        temp2_symbols = list(set(running_symbols) - set(subscribed_symbols))
        Filter.logging.debug(f"Diff Running/Subscribed: {temp2_symbols}")
        subscribe_symbols = list(set(new_symbol) - set(temp_symbols))
        Filter.logging.debug(f"Subscribe: {subscribed_symbols}")
        if temp2_symbols:
            subscribe_symbols = subscribe_symbols + temp2_symbols

        for symbol in subscribe_symbols:
            self.__request_api_endpoint(f"{self.ws_url}/symbol/add/{symbol}")

        return (subscribed_symbols, unsubscribe_symbols, subscribe_symbols)

    def __get_symbols(self):
        subscribed_list = self.__request_api_endpoint(
            f"{self.ws_url}/symbol/list"
        ).json()["result"]
        subscribed_symbols = [
            f"{symbol}"
            for symbol, kline in [item.split("@") for item in subscribed_list]
        ]

        return subscribed_list

    def subscribe_symbol(self, symbol):
        try:
            self.__request_api_endpoint(f"{self.ws_url}/symbol/add/{symbol}")
        except Exception as e:
            Filter.logging.error(
                f"Error adding {symbol} to Moonloader subscription list. Cause {e}"
            )

    def unsubscribe_symbol(self, symbol):
        try:
            self.__request_api_endpoint(f"{self.ws_url}/symbol/remove/{symbol}")
        except Exception as e:
            Filter.logging.error(
                f"Error removing {symbol} from Moonloader subscription list. Cause {e}"
            )

    def __get_symbol_subscription(self):
        subscribed_symbols = self.__get_symbols()

        if self.btc_pulse:
            for symbol in subscribed_symbols:
                if "btcusdt" in symbol:
                    subscribed_symbols.remove(symbol)
                    break

        return subscribed_symbols
