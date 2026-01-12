import requests
import helper
from cachetools import cached, TTLCache
from tenacity import retry, TryAgain, stop_after_attempt, wait_fixed

logging = helper.LoggerFactory.get_logger("logs/filter.log", "filter")


class Filter:
    def __init__(self):
        config = helper.Config()
        self.ws_url = config.get("ws_url", None)
        self.btc_pulse = config.get("btc_pulse", False)
        self.currency = config.get("currency").upper()

    @retry(wait=wait_fixed(10), stop=stop_after_attempt(10))
    def __request_api_endpoint(self, request, headers=None):
        response = None
        try:
            if headers:
                response = requests.get(url=request, headers=headers)
            else:
                response = requests.get(url=request)
        except requests.exceptions.RequestException as e:
            logging.error(f"Error getting response for {request}. Cause: {e}")
            raise TryAgain

        return response

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

    def has_enough_volume(self, range, size, volume):
        result = False
        volume_ranges = ["K", "M", "B", "T"]

        if volume:
            if size and range:
                volume_position_in = volume_ranges.index(volume["range"].upper())
                volume_position_out = volume_ranges.index(range.upper())
                if (
                    float(size) >= float(volume["size"])
                    and volume_position_out == volume_position_in
                ) or volume_position_out > volume_position_in:
                    result = True
        else:
            result = True

        return result

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
            if json_data["status"]["error_code"] == 0:
                for entry in json_data["data"]:
                    if entry["symbol"] == symbol:
                        marketcap = entry["rank"]
                        break
        except Exception as e:
            logging.error(f"Error getting CMC data. Cause: {e}")

        return marketcap
