"""Market filtering helpers for signals."""

from typing import Any

import helper
import httpx
from tenacity import TryAgain, retry, stop_after_attempt, wait_fixed

logging = helper.LoggerFactory.get_logger("logs/filter.log", "filter")


class Filter:
    """Filter helpers for allow/deny lists and volume checks."""

    @retry(wait=wait_fixed(10), stop=stop_after_attempt(10))
    async def __request_api_endpoint(
        self, request: str, headers: dict | None = None
    ) -> Any:
        response = None
        try:
            async with httpx.AsyncClient() as client:
                if headers:
                    response = await client.get(url=request, headers=headers)
                else:
                    response = await client.get(url=request)
                response.raise_for_status()
        except httpx.HTTPError as e:
            logging.error("Error getting response for %s. Cause: %s", request, e)
            raise TryAgain

        return response

    def is_on_allowed_list(self, symbol: str, allow_list: list[str] | None) -> bool:
        """Return True if symbol is in allow list or allow list is empty."""
        result = False
        if allow_list:
            if symbol in allow_list:
                result = True
        else:
            result = True

        return result

    def is_on_deny_list(self, symbol: str, deny_list: list[str] | None) -> bool:
        """Return True if symbol is in deny list."""
        result = False
        if deny_list:
            if symbol in deny_list:
                result = True

        return result

    def is_within_topcoin_limit(
        self, market_cap_rank: int | None, topcoin_limit: int | None
    ) -> bool:
        """Return True if the rank is within the configured limit."""
        result = False
        if topcoin_limit:
            if market_cap_rank:
                if market_cap_rank <= topcoin_limit:
                    result = True
        else:
            result = True

        return result

    def has_enough_volume(
        self, range: str | None, size: float | None, volume: dict[str, Any] | None
    ) -> bool:
        """Return True if volume meets the configured threshold."""
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

    @helper.async_ttl_cache(maxsize=1024, ttl=86400)
    async def get_cmc_marketcap_rank(self, api_key: str, symbol: str) -> Any:
        """Fetch CoinMarketCap market cap rank for the symbol."""
        marketcap = None
        headers = {"X-CMC_PRO_API_KEY": api_key}
        ws_endpoint = "pro-api.coinmarketcap.com"
        ws_context = "v1/cryptocurrency/map"
        start = 1
        limit = 5000
        sort = "cmc_rank"
        url = f"https://{ws_endpoint}/{ws_context}?start={start}&limit={limit}&sort={sort}"
        response = await self.__request_api_endpoint(
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
            logging.error("Error getting CMC data. Cause: %s", e)

        return marketcap
