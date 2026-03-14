"""Exchange client lifecycle management."""

import asyncio
from typing import Any

import ccxt.async_support as ccxt


class ExchangeClientManager:
    """Own lifecycle and market-loading state for one CCXT client."""

    MARKETS_REFRESH_TTL_SECONDS = 300.0

    def __init__(self, logger: Any):
        self._logger = logger
        self.exchange: Any = None
        self._exchange_config: dict[str, Any] | None = None
        self._markets_loaded = False
        self._markets_loaded_ts = 0.0
        self._exchange_lock = asyncio.Lock()

    async def close(self) -> None:
        """Close the underlying exchange client and reset cached state."""
        if self.exchange is None:
            return

        try:
            await self.exchange.close()
        except (ccxt.BaseError, OSError, RuntimeError) as exc:
            self._logger.warning("Failed to close exchange client cleanly: %s", exc)
        finally:
            self.exchange = None
            self._exchange_config = None
            self._markets_loaded = False
            self._markets_loaded_ts = 0.0

    def build_exchange_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Normalize runtime config into the fields that require a client rebuild."""
        return {
            "exchange": config.get("exchange"),
            "key": config.get("key"),
            "secret": config.get("secret"),
            "market": config.get("market", "spot"),
            "dry_run": config.get("dry_run", True),
            "exchange_hostname": config.get("exchange_hostname"),
        }

    async def ensure_exchange(self, config: dict[str, Any]) -> bool:
        """Ensure a client exists and matches the requested config."""
        desired_config = self.build_exchange_config(config)
        async with self._exchange_lock:
            if self.exchange is not None and self._exchange_config == desired_config:
                return False

            if self.exchange is not None:
                await self.close()

            self.exchange = await self._init_exchange(desired_config)
            self._exchange_config = desired_config
            self._markets_loaded = False
            self._markets_loaded_ts = 0.0
            return True

    async def ensure_markets_loaded(self, force_refresh: bool = False) -> None:
        """Ensure exchange markets are loaded and periodically refreshed."""
        if self.exchange is None:
            return

        now = asyncio.get_running_loop().time()
        if (
            not force_refresh
            and self._markets_loaded
            and now - self._markets_loaded_ts < self.MARKETS_REFRESH_TTL_SECONDS
        ):
            return
        async with self._exchange_lock:
            now = asyncio.get_running_loop().time()
            if self.exchange is not None and (
                force_refresh
                or not self._markets_loaded
                or now - self._markets_loaded_ts >= self.MARKETS_REFRESH_TTL_SECONDS
            ):
                await self.exchange.load_markets()
                self._markets_loaded = True
                self._markets_loaded_ts = now

    async def _init_exchange(self, config: dict[str, Any]) -> Any:
        exchange = None

        if config.get("exchange", None):
            options: dict[str, Any] = {"defaultType": config.get("market", "spot")}
            hostname = config.get("exchange_hostname")
            if hostname:
                options["hostname"] = str(hostname).strip()
            exchange_class = getattr(ccxt, config.get("exchange"))
            exchange = exchange_class(
                {
                    "apiKey": config.get("key"),
                    "secret": config.get("secret"),
                    "options": options,
                }
            )
            if hostname:
                self._logger.info(
                    "Using custom exchange hostname '%s' for exchange '%s'.",
                    options["hostname"],
                    config.get("exchange"),
                )
            if config.get("dry_run", True):
                try:
                    exchange.enableDemoTrading(True)
                    self._logger.info(
                        "Enabled CCXT demo trading for exchange '%s'.",
                        config.get("exchange"),
                    )
                except (AttributeError, NotImplementedError, ccxt.BaseError) as exc:
                    raise ValueError(
                        "Dry run requires CCXT enableDemoTrading support, but "
                        f"'{config.get('exchange')}' could not enable demo trading."
                    ) from exc
            exchange.enableRateLimit = True

        return exchange
