"""Market filtering helpers for signals."""

from typing import Any

from service.coin_market_cap import (
    CoinMarketCapRankService,
    MarketCapRankLookup,
    coin_market_cap_rank_service,
)


class Filter:
    """Filter helpers for allow/deny lists and volume checks."""

    def __init__(
        self,
        market_cap_service: CoinMarketCapRankService | None = None,
    ) -> None:
        """Use the shared lifespan-owned rank service by default."""
        self._market_cap_service = market_cap_service or coin_market_cap_rank_service

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

    async def lookup_cmc_marketcap_rank(
        self,
        api_key: str,
        symbol: str,
    ) -> MarketCapRankLookup:
        """Return rank data with availability and snapshot diagnostics."""
        return await self._market_cap_service.lookup(api_key, symbol)

    async def get_cmc_marketcap_rank(self, api_key: str, symbol: str) -> int | None:
        """Return the rank while retaining compatibility with legacy callers."""
        lookup = await self.lookup_cmc_marketcap_rank(api_key, symbol)
        return lookup.rank if lookup.available else None
