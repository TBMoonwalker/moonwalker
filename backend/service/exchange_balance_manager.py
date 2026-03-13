"""Exchange balance cache and balance lookup management."""

import asyncio
from collections.abc import Callable
from typing import Any

import ccxt.async_support as ccxt
from service.exchange_helpers import extract_free_amount


class ExchangeBalanceManager:
    """Own cached balance state and balance-derived helper lookups."""

    def __init__(
        self,
        *,
        logger: Any,
        balance_cache_ttl_seconds: float,
        get_exchange: Callable[[], Any],
        resolve_symbol: Callable[[str], str | None],
    ):
        self._logger = logger
        self._balance_cache_ttl_seconds = balance_cache_ttl_seconds
        self._get_exchange = get_exchange
        self._resolve_symbol = resolve_symbol
        self._balance_lock = asyncio.Lock()
        self._balance_cache: dict[str, Any] | None = None
        self._balance_cache_ts = 0.0

    def reset(self) -> None:
        """Clear any cached balance snapshot."""
        self._balance_cache = None
        self._balance_cache_ts = 0.0

    async def get_balance_snapshot(
        self, force_refresh: bool = False
    ) -> dict[str, Any] | None:
        """Return cached exchange balance snapshot with short TTL."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        now = asyncio.get_running_loop().time()
        if (
            not force_refresh
            and self._balance_cache is not None
            and now - self._balance_cache_ts < self._balance_cache_ttl_seconds
        ):
            return self._balance_cache

        async with self._balance_lock:
            now = asyncio.get_running_loop().time()
            if (
                not force_refresh
                and self._balance_cache is not None
                and now - self._balance_cache_ts < self._balance_cache_ttl_seconds
            ):
                return self._balance_cache

            balance = await exchange.fetch_balance()
            self._balance_cache = balance
            self._balance_cache_ts = now
            return balance

    async def get_available_base_amount(
        self, symbol: str, force_refresh: bool = False
    ) -> float | None:
        """Return currently available base asset amount for a symbol."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        resolved_symbol = self._resolve_symbol(symbol)
        if resolved_symbol is None:
            return None

        base_asset = resolved_symbol.split("/")[0].split(":")[0]
        try:
            balance = await self.get_balance_snapshot(force_refresh=force_refresh)
        except (ccxt.BaseError, RuntimeError, OSError) as exc:
            self._logger.warning(
                "Fetching balance for %s failed: %s", resolved_symbol, exc
            )
            return None

        if balance is None:
            return None
        free_amount = extract_free_amount(balance, base_asset)
        if free_amount is None:
            return None

        try:
            return float(exchange.amount_to_precision(resolved_symbol, free_amount))
        except (ccxt.BaseError, TypeError, ValueError):
            return free_amount

    async def log_remaining_sell_dust(self, symbol: str) -> None:
        """Log remaining base-asset balance after sell execution."""
        remaining_amount = await self.get_available_base_amount(symbol)
        if remaining_amount is None or remaining_amount <= 0:
            return
        self._logger.info(
            "Remaining base amount for %s after sell execution: %s",
            symbol,
            remaining_amount,
        )

    async def get_free_quote_balance(
        self, symbol: str, force_refresh: bool = False
    ) -> float | None:
        """Return currently available quote asset balance for a symbol."""
        resolved_symbol = self._resolve_symbol(symbol)
        if resolved_symbol is None:
            return None

        quote_asset = resolved_symbol.split("/")[1].split(":")[0]
        try:
            balance = await self.get_balance_snapshot(force_refresh=force_refresh)
        except (ccxt.BaseError, RuntimeError, OSError) as exc:
            self._logger.warning(
                "Fetching quote balance for %s failed: %s", symbol, exc
            )
            return None

        if balance is None:
            return None
        return extract_free_amount(balance, quote_asset)

    async def get_free_balance_for_asset(self, asset: str) -> float | None:
        """Return currently available balance for an asset symbol."""
        asset_symbol = str(asset or "").strip().upper()
        if not asset_symbol:
            return None

        try:
            balance = await self.get_balance_snapshot()
        except (ccxt.BaseError, RuntimeError, OSError) as exc:
            self._logger.warning(
                "Fetching free balance for %s failed: %s", asset_symbol, exc
            )
            return None

        if balance is None:
            return None
        return extract_free_amount(balance, asset_symbol)
