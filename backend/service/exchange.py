"""Exchange service for CCXT async operations."""

import asyncio
import json
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import ccxt.async_support as ccxt
import helper
from service.exchange_balance_manager import ExchangeBalanceManager
from service.exchange_buy_manager import ExchangeBuyManager
from service.exchange_capabilities import (
    ExchangeOrderLookupResult,
    ExchangeOrderLookupStatus,
    UnsupportedExchangeCapability,
    build_client_order_params,
    require_exchange_placement_capabilities,
    resolve_exchange_placement_capabilities,
)
from service.exchange_client_manager import ExchangeClientManager
from service.exchange_helpers import precision_step_for_amount
from service.exchange_limit_sell_manager import ExchangeLimitSellManager
from service.exchange_order_lookup import (
    build_parsed_order_status,
    lookup_aggregated_trade,
)
from service.exchange_risk import (
    get_min_notional_for_market,
    is_notional_below_minimum,
    resolve_required_buy_quote,
)
from service.exchange_sell_manager import ExchangeSellManager
from service.exchange_types import ExchangeOrderPayload, ParsedOrderStatus
from tenacity import (
    TryAgain,
    retry,
    stop_after_attempt,
    wait_fixed,
)

logging = helper.LoggerFactory.get_logger("logs/exchange.log", "exchange")


class Exchange:
    """Exchange wrapper for CCXT async operations."""

    HISTORY_RETRY_SLEEP_SECONDS = 1
    HISTORY_MAX_CONSECUTIVE_ERRORS = 5
    BALANCE_CACHE_TTL_SECONDS = 2.0
    BYBIT_SCHEDULE_PAGE_SIZE = 50
    BYBIT_SCHEDULE_MAX_PAGES = 10

    def __init__(
        self,
        *,
        balance_cache_ttl_seconds: float | None = None,
    ) -> None:
        self.utils = helper.Utils()
        self.status = True
        self._client_manager = ExchangeClientManager(logging)
        self._balance_manager = ExchangeBalanceManager(
            logger=logging,
            balance_cache_ttl_seconds=(
                self.BALANCE_CACHE_TTL_SECONDS
                if balance_cache_ttl_seconds is None
                else float(balance_cache_ttl_seconds)
            ),
            get_exchange=lambda: self.exchange,
            resolve_symbol=self._resolve_symbol,
        )
        self._buy_manager = ExchangeBuyManager(
            logger=logging,
            get_exchange=lambda: self.exchange,
        )
        self._sell_manager = ExchangeSellManager(
            logger=logging,
            get_exchange=lambda: self.exchange,
        )
        self._limit_sell_manager = ExchangeLimitSellManager(
            logger=logging,
            get_exchange=lambda: self.exchange,
        )

    @property
    def exchange(self) -> Any:
        """Return the active CCXT exchange client."""
        return self._client_manager.exchange

    @exchange.setter
    def exchange(self, value: Any) -> None:
        """Assign the active CCXT exchange client."""
        self._client_manager.exchange = value

    async def _close_exchange(self) -> None:
        await self._client_manager.close()
        self._balance_manager.reset()

    async def close(self) -> None:
        """Close the underlying exchange client."""
        await self._close_exchange()

    async def _ensure_exchange(self, config: dict[str, Any]) -> None:
        changed = await self._client_manager.ensure_exchange(config)
        if changed:
            self._balance_manager.reset()

    async def _ensure_markets_loaded(self) -> None:
        await self._client_manager.ensure_markets_loaded()

    async def fetch_market_metadata(
        self,
        config: dict[str, Any],
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Return a defensive snapshot of the exchange market metadata."""
        await self._ensure_exchange(config)
        await self._client_manager.ensure_markets_loaded(force_refresh=force_refresh)
        if self.exchange is None:
            return []
        return [
            dict(market)
            for market in self.exchange.markets.values()
            if isinstance(market, dict)
        ]

    async def fetch_spot_delist_schedule(
        self,
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return the production spot delisting schedule when supported.

        Binance demo trading removes the SAPI URL from its CCXT client. Schedule
        checks therefore use a short-lived production client that is isolated
        from order execution. Operators may use either dedicated read-only
        credentials or explicitly reuse the configured trading credentials.
        """
        exchange_id = str(config.get("exchange") or "").strip().lower()
        if exchange_id != "binance":
            raise NotImplementedError(
                "The configured exchange does not expose a spot delist schedule."
            )

        use_trading_credentials = bool(
            config.get("delisting_schedule_use_trading_credentials", False)
        )
        if use_trading_credentials:
            api_key = str(config.get("key") or "").strip()
            api_secret = str(config.get("secret") or "").strip()
            credential_description = "configured trading"
        else:
            api_key = str(config.get("delisting_schedule_api_key") or "").strip()
            api_secret = str(config.get("delisting_schedule_api_secret") or "").strip()
            credential_description = "dedicated production read-only"

        if not api_key or not api_secret:
            raise RuntimeError(
                f"Binance {credential_description} credentials are required "
                "for delisting schedule checks."
            )

        options: dict[str, Any] = {"defaultType": "spot"}
        hostname = str(config.get("exchange_hostname") or "").strip()
        if hostname:
            options["hostname"] = hostname

        exchange_class = getattr(ccxt, exchange_id)
        schedule_exchange = exchange_class(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "options": options,
            }
        )
        schedule_exchange.enableRateLimit = True
        try:
            fetch_schedule = getattr(
                schedule_exchange,
                "sapi_get_spot_delist_schedule",
                None,
            )
            if not callable(fetch_schedule):
                raise NotImplementedError(
                    "The configured exchange does not expose a spot delist schedule."
                )

            response = await fetch_schedule()
            if not isinstance(response, list):
                raise ValueError("Exchange returned an invalid spot delist schedule.")
            return [dict(entry) for entry in response if isinstance(entry, dict)]
        finally:
            try:
                await schedule_exchange.close()
            except (ccxt.BaseError, OSError, RuntimeError) as exc:
                logging.warning(
                    "Failed to close delisting schedule client cleanly: %s",
                    exc,
                )

    async def fetch_bybit_delisting_schedule(
        self,
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return Bybit's public spot delisting announcements.

        Bybit does not publish an authenticated delisting schedule like
        Binance; spot delistings are announced through a public,
        unauthenticated endpoint. A short-lived CCXT client with no
        credentials is therefore sufficient. The schedule is advisory, so a
        transient feed failure must not freeze trading: CCXT market status
        remains the backstop. Operators may supply a hostname override for
        Bybit EU.
        """
        exchange_id = str(config.get("exchange") or "").strip().lower()
        if exchange_id not in ("bybit", "bybiteu"):
            raise NotImplementedError(
                "The configured exchange does not expose a spot delist schedule."
            )

        options: dict[str, Any] = {"defaultType": "spot"}
        hostname = str(config.get("exchange_hostname") or "").strip()
        if hostname:
            options["hostname"] = hostname

        exchange_class = getattr(ccxt, exchange_id)
        schedule_exchange = exchange_class({"options": options})
        schedule_exchange.enableRateLimit = True
        try:
            fetch_announcements = getattr(
                schedule_exchange,
                "public_get_v5_announcements_index",
                None,
            )
            if not callable(fetch_announcements):
                raise NotImplementedError(
                    "The configured exchange does not expose a spot delist schedule."
                )

            schedule: list[dict[str, Any]] = []
            # Bound the work so a large feed cannot stall a refresh loop.
            for page in range(1, self.BYBIT_SCHEDULE_MAX_PAGES + 1):
                response = await fetch_announcements(
                    {
                        "locale": "en-US",
                        "type": "delistings",
                        "page": page,
                        "limit": self.BYBIT_SCHEDULE_PAGE_SIZE,
                    }
                )
                if not isinstance(response, dict):
                    break
                result = response.get("result")
                if not isinstance(result, dict):
                    break
                items = result.get("list")
                if not isinstance(items, list) or not items:
                    break
                for item in items:
                    if isinstance(item, dict):
                        schedule.append(dict(item))
            return schedule
        finally:
            try:
                await schedule_exchange.close()
            except (ccxt.BaseError, OSError, RuntimeError) as exc:
                logging.warning(
                    "Failed to close delisting schedule client cleanly: %s",
                    exc,
                )

    @staticmethod
    def _raise_retryable_exchange_error(action: str, exc: Exception) -> None:
        """Log a retryable exchange-related failure and request a retry."""
        if isinstance(exc, ccxt.ExchangeError):
            logging.error("%s failed due to an exchange error: %s", action, exc)
        elif isinstance(exc, ccxt.NetworkError):
            logging.error("%s failed due to a network error: %s", action, exc)
        elif isinstance(exc, ccxt.BaseError):
            logging.error("%s failed due to an error: %s", action, exc)
        else:
            logging.error("%s failed with: %s", action, exc)
        raise TryAgain

    def _build_notional_check(
        self,
        *,
        is_market_order: bool,
    ) -> Callable[[str, float, float], tuple[bool, float | None, float]]:
        """Build a minimum-notional checker for market or limit orders."""

        def notional_check(
            symbol: str,
            amount: float,
            price: float,
        ) -> tuple[bool, float | None, float]:
            return self._is_notional_below_minimum(
                symbol,
                amount,
                price,
                is_market_order=is_market_order,
            )

        return notional_check

    def _resolve_symbol(self, symbol: str) -> str | None:
        """Resolve a user-provided symbol to the exchange canonical symbol."""
        if not symbol:
            return None
        if self.exchange is None:
            return None

        # Fast path for exact key matches.
        if symbol in self.exchange.markets:
            return symbol

        # Prefer CCXT's own parser/normalizer.
        try:
            market = self.exchange.market(symbol)
            resolved = market.get("symbol") if isinstance(market, dict) else None
            if isinstance(resolved, str):
                return resolved
        except (ccxt.BaseError, TypeError, ValueError):
            pass

        # Bybit and similar exchanges may require contract suffixed symbols
        # like "BTC/USDT:USDT". Try quote-suffixed candidates.
        if "/" in symbol and ":" not in symbol:
            base, quote = symbol.split("/", 1)
            candidates = (
                f"{base}/{quote}:{quote}",
                f"{base}/{quote}:{base}",
            )
            for candidate in candidates:
                if candidate in self.exchange.markets:
                    return candidate
                try:
                    market = self.exchange.market(candidate)
                    resolved = (
                        market.get("symbol") if isinstance(market, dict) else None
                    )
                    if isinstance(resolved, str):
                        return resolved
                except (ccxt.BaseError, TypeError, ValueError):
                    continue

        return None

    async def _resolve_symbol_with_refresh(self, symbol: str) -> str | None:
        """Resolve a symbol and refresh markets once when the cache is stale."""
        resolved_symbol = self._resolve_symbol(symbol)
        if resolved_symbol is not None or self.exchange is None:
            return resolved_symbol

        logging.info(
            "Symbol '%s' not found in current market cache. Refreshing markets and retrying.",
            symbol,
        )
        await self._client_manager.ensure_markets_loaded(force_refresh=True)
        resolved_symbol = self._resolve_symbol(symbol)
        if resolved_symbol is None:
            exchange_config = self._client_manager.get_exchange_config() or {}
            dry_run = bool(exchange_config.get("dry_run", False))
            exchange_name = exchange_config.get("exchange", "unknown")
            logging.warning(
                "Symbol '%s' is still unavailable after market refresh. "
                "This can happen for unsupported demo/testnet pairs or stale signal inputs. "
                "exchange=%s dry_run=%s",
                symbol,
                exchange_name,
                dry_run,
            )
            if dry_run:
                logging.warning(
                    "Symbol '%s' is missing from the %s demo market list. "
                    "Public ticker/watcher data can still exist for live-listed symbols "
                    "even when the demo trading venue does not expose them yet.",
                    symbol,
                    exchange_name,
                )
        return resolved_symbol

    async def get_history_for_symbol(
        self,
        config: dict[str, Any],
        symbol: str,
        timeframe: str,
        limit: int = 1,
        since: int = 0,
        until: int | None = None,
    ) -> list[list[Any]]:
        """Fetch historical OHLCV data for a symbol."""
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        ohlcv = None
        resolved_symbol = self._resolve_symbol(symbol)
        if resolved_symbol is None:
            logging.error("%s not found", symbol)
            return ohlcv

        timeframe_ms = self.exchange.parse_timeframe(timeframe) * 1000
        now = self.exchange.milliseconds()
        upper_bound = min(now, int(until)) if until is not None else now

        all_candles = []
        consecutive_errors = 0

        while since < upper_bound:
            try:
                candles = await self.exchange.fetch_ohlcv(
                    symbol=resolved_symbol,
                    timeframe=timeframe,
                    since=since,
                    limit=limit,
                    **({"params": {"until": upper_bound}} if until is not None else {}),
                )

                if not candles:
                    break

                bounded_candles = [
                    candle
                    for candle in candles
                    if len(candle) > 0 and int(candle[0]) <= upper_bound
                ]
                if not bounded_candles:
                    break

                all_candles.extend(bounded_candles)
                if len(bounded_candles) < len(candles):
                    break
                if bounded_candles[-1][0] >= upper_bound:
                    break

                next_since = bounded_candles[-1][0] + timeframe_ms
                if next_since <= since:
                    logging.warning(
                        "No OHLCV cursor progress for %s on timeframe %s. "
                        "Stopping history fetch to avoid tight loop.",
                        resolved_symbol,
                        timeframe,
                    )
                    break
                since = next_since
                consecutive_errors = 0

            except (ccxt.NetworkError, ccxt.ExchangeError, ccxt.BaseError) as e:
                # Broad catch to continue paging through historical data.
                logging.error("Fetching historical data failed due to an error: %s", e)
                consecutive_errors += 1
                if consecutive_errors >= self.HISTORY_MAX_CONSECUTIVE_ERRORS:
                    logging.error(
                        "Stopping history fetch for %s after %s consecutive errors.",
                        resolved_symbol,
                        consecutive_errors,
                    )
                    break
                await asyncio.sleep(self.HISTORY_RETRY_SLEEP_SECONDS)
            except (TypeError, ValueError, RuntimeError) as e:
                logging.error("Fetching historical data failed due to an error: %s", e)
                consecutive_errors += 1
                if consecutive_errors >= self.HISTORY_MAX_CONSECUTIVE_ERRORS:
                    logging.error(
                        "Stopping history fetch for %s after %s consecutive errors.",
                        resolved_symbol,
                        consecutive_errors,
                    )
                    break
                await asyncio.sleep(self.HISTORY_RETRY_SLEEP_SECONDS)

        return all_candles

    async def get_history_for_symbol_batched(
        self,
        config: dict[str, Any],
        symbol: str,
        timeframe: str,
        since: int = 0,
        until: int | None = None,
        page_size: int = 1000,
        max_candles: int = 20_000,
        page_delay: float = 0.5,
    ) -> list[list[Any]]:
        """Fetch OHLCV in fixed-size pages with rate-limit backoff."""
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        resolved_symbol = self._resolve_symbol(symbol)
        if resolved_symbol is None:
            logging.error("%s not found", symbol)
            return []

        all_candles: list[list[Any]] = []
        seen_timestamps: set[int] = set()
        consecutive_errors = 0
        now = self.exchange.milliseconds()
        upper_bound = min(now, int(until)) if until is not None else now

        current_since = since if since > 0 else 0
        while current_since < upper_bound:
            if len(all_candles) >= max_candles:
                break

            try:
                candles = await self.exchange.fetch_ohlcv(
                    symbol=resolved_symbol,
                    timeframe=timeframe,
                    since=current_since,
                    limit=page_size,
                )
                if not candles:
                    break

                bounded = [
                    c for c in candles if len(c) > 0 and int(c[0]) <= upper_bound
                ]
                if not bounded:
                    break

                new_candles: list[list[Any]] = []
                for candle in bounded:
                    timestamp = int(candle[0])
                    if timestamp in seen_timestamps:
                        continue
                    seen_timestamps.add(timestamp)
                    new_candles.append(candle)

                needed = max_candles - len(all_candles)
                all_candles.extend(new_candles[:needed])

                if len(bounded) < page_size:
                    break

                current_since = int(bounded[-1][0]) + 1
                consecutive_errors = 0
                if len(all_candles) < max_candles and current_since < upper_bound:
                    await asyncio.sleep(page_delay)
            except (ccxt.NetworkError, ccxt.ExchangeError, ccxt.BaseError) as e:
                logging.error("Batch fetch error: %s", e)
                consecutive_errors += 1
                if consecutive_errors >= self.HISTORY_MAX_CONSECUTIVE_ERRORS:
                    break
                await asyncio.sleep(page_delay * (2 ** (consecutive_errors - 1)))
            except (TypeError, ValueError, RuntimeError) as e:
                logging.error("Batch fetch error: %s", e)
                consecutive_errors += 1
                if consecutive_errors >= self.HISTORY_MAX_CONSECUTIVE_ERRORS:
                    break
                await asyncio.sleep(page_delay * (2 ** (consecutive_errors - 1)))

        return all_candles[:max_candles]

    async def get_symbols_for_quote_currency(
        self, config: dict[str, Any], quote_currency: str
    ) -> list[str]:
        """Return exchange symbols filtered by quote currency."""
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        if self.exchange is None:
            return []

        quote = quote_currency.upper()
        symbols: list[str] = []
        for market_symbol, market in self.exchange.markets.items():
            if not isinstance(market, dict):
                continue
            if str(market.get("quote", "")).upper() != quote:
                continue
            if market.get("active") is False:
                continue
            if config.get("market", "spot") == "spot" and market.get("spot") is False:
                continue

            normalized_symbol = market.get("symbol", market_symbol)
            if isinstance(normalized_symbol, str) and "/" in normalized_symbol:
                symbols.append(normalized_symbol)

        return sorted(set(symbols))

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    async def _get_price_for_symbol(
        self,
        pair: str,
        *,
        prefer_ask: bool = False,
    ) -> str:
        """Return a current exchange price with exchange precision.

        Buy execution paths prefer the best ask because it is the immediately
        executable price. Other callers retain the last-trade behavior.
        """
        result = None

        try:
            resolved_pair = await self._resolve_symbol_with_refresh(pair)
            if resolved_pair is None:
                logging.debug(
                    "Could not resolve symbol '%s' for ticker fetch after refresh.",
                    pair,
                )
                return ""
            # Fetch the ticker data for the trading pair
            ticker = await self.exchange.fetch_ticker(resolved_pair)
            raw_price = ticker.get("ask") if prefer_ask else ticker.get("last")
            if not raw_price:
                raw_price = ticker.get("last")
            if not raw_price:
                logging.debug(
                    "Ticker for %s has no usable price yet. Will retry.",
                    resolved_pair,
                )
                raise TryAgain
            actual_price = float(raw_price)
            result = self.exchange.price_to_precision(resolved_pair, actual_price)
        except TryAgain:
            raise
        except (
            ccxt.ExchangeError,
            ccxt.NetworkError,
            ccxt.BaseError,
            TypeError,
            ValueError,
            RuntimeError,
        ) as exc:
            self._raise_retryable_exchange_error("Fetching ticker data", exc)

        return result

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    async def _get_precision_for_symbol(self, pair: str) -> Any:
        """Return exchange amount precision for a symbol."""
        result = None

        try:
            resolved_pair = await self._resolve_symbol_with_refresh(pair)
            if resolved_pair is None:
                logging.debug(
                    "Could not resolve symbol '%s' for precision lookup after refresh.",
                    pair,
                )
                return None
            market = self.exchange.market(resolved_pair)
            result = market["precision"]["amount"]
        except (
            ccxt.ExchangeError,
            ccxt.NetworkError,
            ccxt.BaseError,
            TypeError,
            ValueError,
            RuntimeError,
        ) as exc:
            self._raise_retryable_exchange_error("Fetching market data", exc)

        return result

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    async def _get_trades_for_symbol(
        self,
        symbol: str,
        orderid: str,
        order_check_range_seconds: int,
        order_timestamp: int | None = None,
    ) -> dict | None:
        await asyncio.sleep(1)
        try:
            return await lookup_aggregated_trade(
                self.exchange,
                logger=logging,
                symbol=symbol,
                orderid=orderid,
                order_check_range_seconds=order_check_range_seconds,
                order_timestamp=order_timestamp,
            )
        except (
            ccxt.NetworkError,
            ccxt.ExchangeError,
            ccxt.BaseError,
            TypeError,
            ValueError,
            RuntimeError,
            KeyError,
        ) as exc:
            self._raise_retryable_exchange_error("Fetch trade order", exc)
        return None

    async def _parse_order_status(
        self,
        order: ExchangeOrderPayload,
        *,
        order_check_range_seconds: int,
    ) -> ParsedOrderStatus:
        trade = await self._get_trades_for_symbol(
            order["symbol"],
            order["id"],
            order_check_range_seconds,
            int(order.get("timestamp") or 0),
        )
        if not trade:
            logging.info(
                "Getting trades for %s failed - using information of order.",
                order["symbol"],
            )
        return build_parsed_order_status(order, trade)

    @retry(wait=wait_fixed(1), stop=stop_after_attempt(10))
    async def _get_amount_from_symbol(
        self,
        ordersize: float,
        symbol: str,
        price: float | str | None = None,
    ) -> str:
        resolved_symbol = await self._resolve_symbol_with_refresh(symbol)
        if resolved_symbol is None:
            logging.debug(
                "Could not resolve symbol '%s' for amount lookup after refresh.",
                symbol,
            )
            return ""
        resolved_price = (
            price
            if price is not None and float(price) > 0
            else await self._get_price_for_symbol(resolved_symbol, prefer_ask=True)
        )
        amount = None
        try:
            amount = self.exchange.amount_to_precision(
                resolved_symbol, float(ordersize) / float(resolved_price)
            )
        except (
            ccxt.NetworkError,
            ccxt.ExchangeError,
            ccxt.BaseError,
            TypeError,
            ValueError,
            RuntimeError,
        ) as exc:
            self._raise_retryable_exchange_error(
                f"Getting amount for {symbol}",
                exc,
            )

        return amount

    def _reduce_amount_by_step(
        self, symbol: str, current_amount: float, steps: int
    ) -> float:
        """Reduce amount by precision step and return exchange-formatted value."""
        formatted = self.exchange.amount_to_precision(symbol, current_amount)
        step = precision_step_for_amount(formatted)
        reduced = max(0.0, float(formatted) - (step * max(1, steps)))
        return float(self.exchange.amount_to_precision(symbol, reduced))

    def _get_min_notional_for_symbol(
        self, symbol: str, *, is_market_order: bool
    ) -> float | None:
        """Resolve minimum notional for a symbol from CCXT market metadata."""
        if self.exchange is None:
            return None

        try:
            market = self.exchange.market(symbol)
        except (ccxt.BaseError, TypeError, ValueError):
            return None
        return get_min_notional_for_market(
            market,
            is_market_order=is_market_order,
        )

    def _is_notional_below_minimum(
        self, symbol: str, amount: float, price: float, *, is_market_order: bool
    ) -> tuple[bool, float | None, float]:
        """Check whether an order notional is below exchange minimum."""
        min_notional = self._get_min_notional_for_symbol(
            symbol, is_market_order=is_market_order
        )
        return is_notional_below_minimum(amount, price, min_notional)

    def _resolve_required_buy_quote(self, order: dict[str, Any]) -> float | None:
        """Return required quote amount for a buy order."""
        return resolve_required_buy_quote(order)

    @staticmethod
    def _get_order_check_range_seconds(config: dict[str, Any]) -> int:
        """Return configured trade lookup window in seconds."""
        try:
            return int(config.get("order_check_range", 300))
        except (TypeError, ValueError, AttributeError):
            return 300

    async def _get_available_base_amount(
        self, symbol: str, force_refresh: bool = False
    ) -> float | None:
        """Return currently available base asset amount for a symbol."""
        return await self._balance_manager.get_available_base_amount(
            symbol,
            force_refresh=force_refresh,
        )

    async def _log_remaining_sell_dust(self, symbol: str) -> None:
        """Log remaining base-asset balance after sell execution.

        Small leftovers are common due to precision and minimum-order constraints.
        This method keeps the behavior explicit and observable without adding
        exchange-specific convert/dust trading logic.
        """
        await self._balance_manager.log_remaining_sell_dust(symbol)

    async def get_free_quote_balance(
        self, config: dict[str, Any], symbol: str, force_refresh: bool = False
    ) -> float | None:
        """Return currently available quote asset balance for a symbol."""
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        return await self._balance_manager.get_free_quote_balance(
            symbol,
            force_refresh=force_refresh,
        )

    def _get_capped_buy_price(self, symbol: str, maximum_price: float) -> float:
        """Return a valid exchange price without exceeding the execution cap."""
        price = float(self.exchange.price_to_precision(symbol, maximum_price))
        if price > maximum_price:
            market = self.exchange.market(symbol)
            price = float(
                ccxt.decimal_to_precision(
                    str(maximum_price),
                    ccxt.TRUNCATE,
                    market["precision"]["price"],
                    self.exchange.precisionMode,
                    self.exchange.paddingMode,
                )
            )
        if price <= 0:
            raise ValueError("Execution cap is below the minimum price tick")
        return price

    async def _fetch_bybiteu_buy_limit(self, symbol: str) -> Decimal:
        """Read Bybit EU's validated dynamic spot limit without losing precision."""
        market_id = self.exchange.market(symbol)["id"]
        async with asyncio.timeout(10):
            response = await self.exchange.public_get_v5_market_price_limit(
                {"category": "spot", "symbol": market_id}
            )
        if (
            not isinstance(response, dict)
            or type(response.get("retCode")) is not int
            or response["retCode"] != 0
        ):
            raise ValueError("Bybit EU returned an invalid price-limit response")
        result = response.get("result")
        if not isinstance(result, dict) or result.get("symbol") != market_id:
            raise ValueError("Bybit EU price limit does not match the requested symbol")
        timestamp = result.get("ts")
        if (
            not isinstance(timestamp, str)
            or not timestamp.isdigit()
            or len(timestamp) > 20
        ):
            raise ValueError("Bybit EU price limit has no valid timestamp")
        age_ms = time.time() * 1000 - int(timestamp)
        if not -5000 <= age_ms <= 10000:
            raise ValueError("Bybit EU price limit is stale or future-dated")
        raw_ceiling = result.get("buyLmt")
        if type(raw_ceiling) not in (str, int, float):
            raise ValueError("Bybit EU maximum buy price has an invalid type")
        from service.exchange_types import decimal_evidence

        band_ceiling = Decimal(decimal_evidence(raw_ceiling))
        if not band_ceiling.is_finite() or band_ceiling <= 0:
            raise ValueError("Bybit EU maximum buy price is invalid")
        return band_ceiling

    async def _get_bybiteu_buy_ceiling(self, symbol: str, ceiling: float) -> float:
        """Keep legacy DCA's float boundary while sharing validated venue evidence."""
        return min(ceiling, float(await self._fetch_bybiteu_buy_limit(symbol)))

    async def get_spot_buy_ceiling(
        self, symbol: str, maximum: str, config: dict[str, Any]
    ) -> str:
        """Clamp an exact accumulation ceiling before precision, sizing and claim."""
        from service.exchange_types import canonical_decimal

        ceiling = Decimal(canonical_decimal(maximum, positive=True))
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        if getattr(self.exchange, "id", None) == "bybiteu":
            ceiling = min(ceiling, await self._fetch_bybiteu_buy_limit(symbol))
        return format(ceiling, "f")

    def _is_bybiteu_price_band_rejection(self, error: Exception) -> bool:
        """Recognize only a definitive Bybit EU maximum-buy-price rejection."""
        if getattr(self.exchange, "id", None) != "bybiteu":
            return False
        message = str(error)
        try:
            payload = json.loads(message[message.index("{") :])
        except (ValueError, TypeError):
            return False
        return isinstance(payload, dict) and payload.get("retCode") == 170193

    async def get_minimum_buy_notional(
        self,
        config: dict[str, Any],
        symbol: str,
        *,
        is_market_order: bool = True,
        amount_sizing_price: float | None = None,
    ) -> float | None:
        """Return the precision-safe minimum quote notional for a buy order."""
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        resolved_symbol = await self._resolve_symbol_with_refresh(symbol)
        if resolved_symbol is None:
            return None
        minimum_notional = self._get_min_notional_for_symbol(
            resolved_symbol,
            is_market_order=is_market_order,
        )
        if (
            minimum_notional is None
            or amount_sizing_price is None
            or amount_sizing_price <= 0
        ):
            return minimum_notional

        try:
            precise_price = (
                float(
                    self.exchange.price_to_precision(
                        resolved_symbol,
                        amount_sizing_price,
                    )
                )
                if is_market_order
                else self._get_capped_buy_price(resolved_symbol, amount_sizing_price)
            )
            raw_amount = minimum_notional / precise_price
            formatted_amount = self.exchange.amount_to_precision(
                resolved_symbol,
                raw_amount,
            )
            precise_amount = float(formatted_amount)
            estimated_notional = precise_amount * precise_price
            if estimated_notional + 1e-12 < minimum_notional:
                amount_step = precision_step_for_amount(formatted_amount)
                precise_amount = float(
                    self.exchange.amount_to_precision(
                        resolved_symbol,
                        precise_amount + amount_step,
                    )
                )
                estimated_notional = precise_amount * precise_price
                if estimated_notional + 1e-12 < minimum_notional:
                    return None
                estimated_notional += amount_step * precise_price * 0.001
            return max(minimum_notional, estimated_notional)
        except (ccxt.BaseError, TypeError, ValueError, ZeroDivisionError):
            return None

    async def get_free_balance_for_asset(
        self, config: dict[str, Any], asset: str
    ) -> float | None:
        """Return currently available balance for an asset symbol (e.g. USDC)."""
        await self._ensure_exchange(config)
        return await self._balance_manager.get_free_balance_for_asset(asset)

    async def _resolve_sell_amount(
        self, symbol: str, requested_amount: float
    ) -> tuple[str, float] | None:
        """Resolve sell amount capped by current free balance."""
        resolved_symbol = await self._resolve_symbol_with_refresh(symbol)
        if resolved_symbol is None:
            return None

        target_amount = max(0.0, float(requested_amount))
        available_amount = await self._get_available_base_amount(
            resolved_symbol, force_refresh=True
        )
        if available_amount is not None:
            target_amount = min(target_amount, available_amount)

        try:
            target_amount = float(
                self.exchange.amount_to_precision(resolved_symbol, target_amount)
            )
        except (ccxt.BaseError, TypeError, ValueError):
            pass

        if target_amount <= 0:
            return None

        return resolved_symbol, target_amount

    async def submit_preflighted_spot_buy(
        self,
        *,
        symbol: str,
        amount: str,
        price: str,
        client_order_id: str,
        config: dict[str, Any],
    ) -> Any:
        """Submit one journaled, precision-checked IOC buy and return raw evidence.

        The owning lifecycle supplies exact preflighted strings and retains all
        unknown outcomes. This boundary never resizes, retries or runs the DCA
        finalizer. It is not registered as a controller or runtime producer.
        """
        if type(config.get("dry_run")) is not bool or config.get("market") != "spot":
            raise ValueError("A validated demo or live spot configuration is required.")
        if not client_order_id:
            raise ValueError("A durable client order identity is required.")
        capabilities = require_exchange_placement_capabilities(
            config, order_type="limit"
        )
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        params = build_client_order_params(client_order_id, capabilities)
        params["timeInForce"] = "IOC"
        return await self._buy_manager.submit_buy_once(
            symbol=symbol, order_type="limit", amount=amount, price=price, params=params
        )

    async def submit_preflighted_spot_sell(
        self,
        *,
        symbol: str,
        amount: str,
        client_order_id: str,
        config: dict[str, Any],
    ) -> Any:
        """Submit one owned manual market sale without retry or DCA finalization."""
        if type(config.get("dry_run")) is not bool or config.get("market") != "spot":
            raise ValueError("A validated demo or live spot configuration is required.")
        if not client_order_id:
            raise ValueError("A durable client order identity is required.")
        capabilities = require_exchange_placement_capabilities(
            config, order_type="market"
        )
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        return await self._sell_manager.submit_market_sell_once(
            symbol=symbol,
            amount=amount,
            params=build_client_order_params(client_order_id, capabilities),
        )

    async def fetch_spot_order(
        self,
        symbol: str,
        order_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Fetch one exchange order by symbol and id."""
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        exchange = self.exchange
        if exchange is None:
            return None
        resolved_symbol = await self._resolve_symbol_with_refresh(symbol)
        if resolved_symbol is None:
            return None
        try:
            return await exchange.fetch_order(order_id, resolved_symbol)
        except (ccxt.BaseError, RuntimeError, TypeError, ValueError) as exc:
            logging.warning(
                "Fetching order %s for %s failed: %s",
                order_id,
                symbol,
                exc,
            )
            return None

    async def read_spot_order_executions(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Read at most 1000 authenticated fills for exactly this order, never a wallet history."""
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        exchange = self.exchange
        if exchange is None or not getattr(exchange, "has", {}).get("fetchOrderTrades"):
            raise ccxt.NotSupported("Order-specific execution lookup is unavailable.")
        return await exchange.fetch_order_trades(
            order["id"], order["symbol"], None, 1000
        )

    async def lookup_spot_order(
        self,
        symbol: str,
        config: dict[str, Any],
        *,
        exchange_order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> ExchangeOrderLookupResult:
        """Look up a durable placement without conflating absence and I/O failure."""
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        exchange = self.exchange
        if exchange is None:
            return ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.UNAVAILABLE,
                error_message="Exchange client is unavailable.",
            )
        resolved_symbol = await self._resolve_symbol_with_refresh(symbol)
        if resolved_symbol is None:
            return ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.UNAVAILABLE,
                error_message=f"Symbol {symbol} is unavailable.",
            )
        normalized_exchange_id = str(exchange_order_id or "").strip()
        normalized_client_id = str(client_order_id or "").strip()
        if not normalized_exchange_id and not normalized_client_id:
            return ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.UNAVAILABLE,
                error_message="Placement has no exchange or client order identity.",
            )

        capabilities = resolve_exchange_placement_capabilities(config)
        if (
            not normalized_exchange_id
            and normalized_client_id
            and capabilities is not None
            and capabilities.client_order_lookup_via_order_lists
        ):
            return await self._lookup_spot_order_by_client_id_in_order_lists(
                exchange=exchange,
                symbol=resolved_symbol,
                client_order_id=normalized_client_id,
                lookup_parameter=capabilities.client_order_lookup_parameter,
            )

        lookup_id = normalized_exchange_id or normalized_client_id
        params = (
            {"clientOrderId": normalized_client_id}
            if not normalized_exchange_id and normalized_client_id
            else {}
        )
        try:
            order = await exchange.fetch_order(
                lookup_id,
                resolved_symbol,
                params,
            )
        except ccxt.OrderNotFound as exc:
            return ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.NOT_FOUND,
                error_message=str(exc),
            )
        except (
            ccxt.NetworkError,
            ccxt.ExchangeError,
            ccxt.BaseError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logging.warning(
                "Durable order lookup failed for %s (exchange_id=%s client_id=%s): %s",
                symbol,
                normalized_exchange_id or None,
                normalized_client_id or None,
                exc,
            )
            return ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.UNAVAILABLE,
                error_message=str(exc),
            )
        if not isinstance(order, dict) or not order:
            return ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.UNAVAILABLE,
                error_message="Exchange returned an empty order lookup result.",
            )
        return ExchangeOrderLookupResult(
            status=ExchangeOrderLookupStatus.FOUND,
            order=dict(order),
        )

    async def _lookup_spot_order_by_client_id_in_order_lists(
        self,
        *,
        exchange: Any,
        symbol: str,
        client_order_id: str,
        lookup_parameter: str,
    ) -> ExchangeOrderLookupResult:
        """Query Bybit-style order lists by their native client identifier."""
        params = {lookup_parameter: client_order_id}
        lookup_error: Exception | None = None
        for fetch_orders in (
            exchange.fetch_open_orders,
            exchange.fetch_closed_orders,
            exchange.fetch_canceled_orders,
        ):
            try:
                orders = await fetch_orders(symbol, None, None, params)
            except (
                ccxt.NetworkError,
                ccxt.ExchangeError,
                ccxt.BaseError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                lookup_error = exc
                continue
            for order in orders or []:
                if not isinstance(order, dict):
                    continue
                info = order.get("info")
                native_client_id = (
                    info.get(lookup_parameter) if isinstance(info, dict) else None
                )
                if str(order.get("clientOrderId") or native_client_id or "") == (
                    client_order_id
                ):
                    return ExchangeOrderLookupResult(
                        status=ExchangeOrderLookupStatus.FOUND,
                        order=dict(order),
                    )

        if lookup_error is not None:
            logging.warning(
                "Durable client-order lookup failed for %s (client_id=%s): %s",
                symbol,
                client_order_id,
                lookup_error,
            )
            return ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.UNAVAILABLE,
                error_message=str(lookup_error),
            )
        return ExchangeOrderLookupResult(
            status=ExchangeOrderLookupStatus.NOT_FOUND,
            error_message="No order exists for the client order identity.",
        )

    async def cancel_spot_order(
        self,
        symbol: str,
        order_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Cancel one exchange order and return its latest status if available."""
        try:
            require_exchange_placement_capabilities(
                config,
                order_type="limit",
            )
        except UnsupportedExchangeCapability as exc:
            logging.error("%s", exc)
            return None
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        resolved_symbol = await self._resolve_symbol_with_refresh(symbol)
        if resolved_symbol is None:
            return None
        await self._limit_sell_manager.cancel_order_safe(resolved_symbol, order_id)
        return await self.fetch_spot_order(resolved_symbol, order_id, config)
