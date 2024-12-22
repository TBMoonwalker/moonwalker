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
    def __request_api_endpoint(self, request, headers=None):
        response = None
        try:
            if headers:
                response = requests.get(url=request, headers=headers)
            else:
                response = requests.get(url=request)
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
    def ema_slope(self, symbol, timeframe, length):
        ema_slope_response = self.__request_api_endpoint(
            f"{self.ws_url}/indicators/ema_slope/{symbol}/{timeframe}/{length}"
        )

        return ema_slope_response

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
            if "BTCUSDT" not in subscribed_symbols:
                self.__request_api_endpoint(f"{self.ws_url}/symbol/add/BTC")
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
            headers,
        )

        try:
            json_data = response.json()
        except Exception as e:
            Filter.logging.error(f"Error getting CMC data. Cause: {e}")

        if json_data["status"]["error_code"] == 0:
            for entry in json_data["data"]:
                if entry["symbol"] == symbol:
                    marketcap = entry["rank"]

        return marketcap

    def __get_symbols(self):
        subscribed_list = self.__request_api_endpoint(
            f"{self.ws_url}/symbol/list"
        ).json()["result"]
        subscribed_symbols = [
            f"{symbol}"
            for symbol, kline in [item.split("@") for item in subscribed_list]
        ]

        return subscribed_symbols

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
