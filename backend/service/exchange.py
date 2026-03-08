"""Exchange service for CCXT async operations."""

import asyncio
from typing import Any

import ccxt.async_support as ccxt
import helper
from tenacity import TryAgain, retry, stop_after_attempt, wait_fixed

logging = helper.LoggerFactory.get_logger("logs/exchange.log", "exchange")


class Exchange:
    """Exchange wrapper for CCXT async operations."""

    HISTORY_RETRY_SLEEP_SECONDS = 1
    HISTORY_MAX_CONSECUTIVE_ERRORS = 5
    BALANCE_CACHE_TTL_SECONDS = 2.0

    def __init__(
        self,
    ):
        self.utils = helper.Utils()
        self.exchange = None
        self.config = None
        self.status = True
        Exchange.sell_retry_count = 0
        self._exchange_config = None
        self._markets_loaded = False
        self._exchange_lock = asyncio.Lock()
        self._balance_lock = asyncio.Lock()
        self._balance_cache: dict[str, Any] | None = None
        self._balance_cache_ts = 0.0
        self._last_buy_precheck_result: dict[str, Any] | None = None

    async def __close_exchange(self) -> None:
        if self.exchange is None:
            return

        try:
            await self.exchange.close()
        except (ccxt.BaseError, OSError, RuntimeError) as exc:
            logging.warning("Failed to close exchange client cleanly: %s", exc)
        finally:
            self.exchange = None
            self._markets_loaded = False
            self._exchange_config = None
            self._balance_cache = None
            self._balance_cache_ts = 0.0

    async def close(self) -> None:
        """Close the underlying exchange client."""
        await self.__close_exchange()

    def __build_exchange_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "exchange": config.get("exchange"),
            "key": config.get("key"),
            "secret": config.get("secret"),
            "market": config.get("market", "spot"),
            "dry_run": config.get("dry_run", True),
            "exchange_hostname": config.get("exchange_hostname"),
        }

    async def __ensure_exchange(self, config: dict[str, Any]) -> None:
        desired_config = self.__build_exchange_config(config)
        async with self._exchange_lock:
            if self.exchange is not None and self._exchange_config == desired_config:
                return

            if self.exchange is not None:
                await self.__close_exchange()

            self.exchange = await self.__init_exchange(desired_config)
            self._exchange_config = desired_config
            self._markets_loaded = False

    async def __ensure_markets_loaded(self) -> None:
        if self._markets_loaded:
            return
        async with self._exchange_lock:
            if not self._markets_loaded:
                await self.exchange.load_markets()
                self._markets_loaded = True

    def __resolve_symbol(self, symbol: str) -> str | None:
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

    @retry(wait=wait_fixed(1), stop=stop_after_attempt(10))
    async def parse_iso_timestamp(self, config: dict[str, Any], date: str) -> int:
        """Parse an ISO-8601 date string using the exchange parser."""
        await self.__ensure_exchange(config)
        timestamp = None
        try:
            timestamp = self.exchange.parse8601(date)
        except ccxt.ExchangeError as e:
            logging.error("Error converting timestamp due to an exchange error: %s", e)
            raise TryAgain
        except ccxt.NetworkError as e:
            logging.error("Error converting timestamp due to a network error: %s", e)
            raise TryAgain
        except ccxt.BaseError as e:
            logging.error("Converting timestamp failed due to an error: %s", e)
            raise TryAgain
        except (TypeError, ValueError, RuntimeError) as e:
            # Broad catch to retry on unexpected exchange errors.
            logging.error("Converting timestamp failed with: %s", e)
            raise TryAgain

        return timestamp

    async def get_history_for_symbol(
        self,
        config: dict[str, Any],
        symbol: str,
        timeframe: str,
        limit: int = 1,
        since: int = 0,
    ) -> list[list[Any]]:
        """Fetch historical OHLCV data for a symbol."""
        await self.__ensure_exchange(config)
        await self.__ensure_markets_loaded()
        ohlcv = None
        resolved_symbol = self.__resolve_symbol(symbol)
        if resolved_symbol is None:
            logging.error("%s not found", symbol)
            return ohlcv

        timeframe_ms = self.exchange.parse_timeframe(timeframe) * 1000
        now = self.exchange.milliseconds()

        all_candles = []
        consecutive_errors = 0

        while since < now:
            try:
                candles = await self.exchange.fetch_ohlcv(
                    symbol=resolved_symbol,
                    timeframe=timeframe,
                    since=since,
                    limit=limit,
                )

                if not candles:
                    break

                all_candles.extend(candles)

                next_since = candles[-1][0] + timeframe_ms
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

    async def get_symbols_for_quote_currency(
        self, config: dict[str, Any], quote_currency: str
    ) -> list[str]:
        """Return exchange symbols filtered by quote currency."""
        await self.__ensure_exchange(config)
        await self.__ensure_markets_loaded()
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
    async def __get_price_for_symbol(self, pair: str) -> str:
        """Gets the actual price for the given symbol/currency pair

        Parameters
        ----------
        pair: string
           Pair - has to be in format "symbol/currency" (Example: BTC/USDT)

        Returns
        -------
        int
            Actual price with correct precision for that pair
        """
        result = None

        try:
            resolved_pair = self.__resolve_symbol(pair)
            if resolved_pair is None:
                logging.debug(
                    "Could not resolve symbol '%s' for ticker fetch. Will retry.",
                    pair,
                )
                raise TryAgain
            # Fetch the ticker data for the trading pair
            ticker = await self.exchange.fetch_ticker(resolved_pair)
            # Extract the actual price from the ticker data
            if not ticker["last"]:
                logging.debug(
                    "Ticker for %s has no 'last' price yet. Will retry.", resolved_pair
                )
                raise TryAgain
            actual_price = float(ticker["last"])
            result = self.exchange.price_to_precision(resolved_pair, actual_price)
        except ccxt.ExchangeError as e:
            logging.error(
                "Fetching ticker messages failed due to an exchange error: %s", e
            )
            raise TryAgain
        except ccxt.NetworkError as e:
            logging.error(
                "Fetching ticker messages failed due to a network error: %s", e
            )
            raise TryAgain
        except ccxt.BaseError as e:
            logging.error("Fetching ticker messages failed due to an error: %s", e)
            raise TryAgain
        except TryAgain:
            raise
        except (TypeError, ValueError, RuntimeError) as e:
            # Broad catch to retry on unexpected exchange errors.
            logging.error(
                "Fetching ticker messages failed with unexpected error type %s: %r",
                type(e).__name__,
                e,
            )
            raise TryAgain

        return result

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    async def __get_precision_for_symbol(self, pair: str) -> Any:

        result = None

        try:
            resolved_pair = self.__resolve_symbol(pair)
            if resolved_pair is None:
                raise TryAgain
            market = self.exchange.market(resolved_pair)
            result = market["precision"]["amount"]
        except ccxt.ExchangeError as e:
            logging.error("Fetching market data failed due to an exchange error: %s", e)
            raise TryAgain
        except ccxt.NetworkError as e:
            logging.error("Fetching market data failed due to a network error: %s", e)
            raise TryAgain
        except ccxt.BaseError as e:
            logging.error("Fetching market data failed due to an error: %s", e)
            raise TryAgain
        except (TypeError, ValueError, RuntimeError) as e:
            # Broad catch to retry on unexpected exchange errors.
            logging.error("FFetching market data failed failed with: %s", e)
            raise TryAgain

        return result

    def __get_demo_taker_fee_for_symbol(self, symbol: str) -> float:
        """Return the static market taker fee for demo trading mode."""
        resolved_symbol = self.__resolve_symbol(symbol)
        if resolved_symbol is None:
            raise ValueError(f"No market available for symbol {symbol}")
        market = self.exchange.market(resolved_symbol)
        taker_fee = market.get("taker")
        if taker_fee is None:
            raise ValueError(f"No market taker fee available for symbol {symbol}")
        return float(taker_fee)

    @staticmethod
    def __is_matching_order_id(candidate_order_id: Any, expected_order_id: str) -> bool:
        """Compare order ids safely across string/int exchange payloads."""
        if candidate_order_id is None:
            return False
        return str(candidate_order_id) == str(expected_order_id)

    async def __fetch_my_trades_for_order(
        self, symbol: str, orderid: str, since: int
    ) -> list[dict[str, Any]]:
        """Fetch account trades and filter to one order id."""
        try:
            orderlist = await self.exchange.fetch_my_trades(symbol, since, 1000)
        except TypeError:
            # Some CCXT adapters ignore limit argument.
            orderlist = await self.exchange.fetch_my_trades(symbol, since)
        return [
            order
            for order in (orderlist or [])
            if self.__is_matching_order_id(order.get("order"), orderid)
        ]

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    async def __get_trades_for_symbol(
        self, symbol: str, orderid: str, order_timestamp: int | None = None
    ) -> dict | None:
        trade = None
        await asyncio.sleep(1)
        order_check_range_seconds = int(self.config.get("order_check_range", 300))
        since = self.exchange.milliseconds() - (order_check_range_seconds * 1000)
        if order_timestamp:
            # Ensure we include all partial fills from order placement onward.
            since = min(int(order_timestamp) - 1000, since)
        try:
            trade = {}
            matched_orders: list[dict[str, Any]] = []

            # Prefer direct per-order trade lookup where supported by exchange.
            try:
                fetched = await self.exchange.fetch_order_trades(orderid, symbol)
                matched_orders = [
                    order
                    for order in (fetched or [])
                    if self.__is_matching_order_id(order.get("order"), orderid)
                ]
            except (ccxt.BaseError, TypeError, ValueError):
                matched_orders = []

            if not matched_orders:
                matched_orders = await self.__fetch_my_trades_for_order(
                    symbol, orderid, since
                )
            if not matched_orders and order_timestamp:
                # Fallback for delayed split fills that exceed configured range.
                matched_orders = await self.__fetch_my_trades_for_order(
                    symbol, orderid, int(order_timestamp) - 86_400_000
                )

            if matched_orders:
                trade = self.__aggregate_matched_trades(matched_orders, symbol, orderid)
        except ccxt.NetworkError as e:
            logging.error("Fetch trade order failed due to a network error: %s", e)
            raise TryAgain
        except ccxt.ExchangeError as e:
            logging.error("Fetch trade order failed due to an exchange error: %s", e)
            raise TryAgain
        except ccxt.BaseError as e:
            logging.error("Fetch trade order failed due to an error: %s", e)
            raise TryAgain
        except (TypeError, ValueError, RuntimeError, KeyError) as e:
            # Broad catch to retry on unexpected exchange errors.
            logging.error("Fetch trade order failed with: %s", e)
            raise TryAgain

        return trade

    def __aggregate_matched_trades(
        self, matched_orders: list[dict[str, Any]], symbol: str, orderid: str
    ) -> dict[str, Any]:
        logging.debug(
            "Orderlist for %s with orderid: %s: %s",
            symbol,
            orderid,
            matched_orders,
        )

        amount = 0.0
        fee = 0.0
        cost = 0.0
        base_fee = 0.0

        for order in matched_orders:
            amount += float(order["amount"])
            fee_data = order.get("fee") or {}
            fee_cost = float(fee_data.get("cost") or 0.0)
            fee += fee_cost
            cost += float(order["cost"])
            fee_currency = str(fee_data.get("currency") or "").upper()
            base_asset = str(order.get("symbol", symbol)).split("/")[0].upper()
            side = str(order.get("side") or "").lower()
            if side == "buy" and fee_currency == base_asset:
                base_fee += fee_cost

        last_order = max(matched_orders, key=lambda o: int(o.get("timestamp") or 0))

        trade = {}
        trade["cost"] = cost
        trade["fee"] = fee
        trade["base_fee"] = base_fee
        trade["amount"] = amount
        trade["timestamp"] = last_order["timestamp"]
        # Use weighted average execution price across all partial fills.
        trade["price"] = (cost / amount) if amount > 0 else last_order["price"]
        trade["order"] = last_order["order"]
        trade["symbol"] = last_order["symbol"]
        trade["side"] = last_order["side"]
        # Store numeric aggregated fee to avoid partial-fill truncation.
        trade["fee_cost"] = fee

        return trade

    async def __parse_order_status(self, order: dict[str, Any]) -> dict[str, Any]:
        data = {}

        trade = await self.__get_trades_for_symbol(
            order["symbol"], order["id"], int(order.get("timestamp") or 0)
        )
        if trade:
            data["timestamp"] = trade["timestamp"]
            data["amount"] = float(trade["amount"])
            data["total_amount"] = float(trade["amount"])
            data["price"] = trade["price"]
            data["orderid"] = trade["order"]
            data["symbol"] = trade["symbol"]
            data["side"] = trade["side"]
            data["amount_fee"] = trade["fee_cost"]
            data["base_fee"] = float(trade.get("base_fee") or 0.0)
            data["ordersize"] = order["cost"]
        else:
            logging.info(
                "Getting trades for %s failed - using information of order.",
                order["symbol"],
            )
            data["timestamp"] = order["timestamp"]
            data["amount"] = float(order["amount"])
            data["total_amount"] = float(order["amount"])
            data["price"] = order["price"]
            data["orderid"] = order["id"]
            data["symbol"] = order["symbol"]
            data["side"] = order["side"]
            data["amount_fee"] = order["fee"]
            data["base_fee"] = 0.0
            data["ordersize"] = order["cost"]

        return data

    @retry(wait=wait_fixed(1), stop=stop_after_attempt(10))
    async def __get_amount_from_symbol(self, ordersize: float, symbol: str) -> str:
        resolved_symbol = self.__resolve_symbol(symbol)
        if resolved_symbol is None:
            raise TryAgain
        price = await self.__get_price_for_symbol(resolved_symbol)
        amount = None
        try:
            amount = self.exchange.amount_to_precision(
                resolved_symbol, float(ordersize) / float(price)
            )
        except ccxt.NetworkError as e:
            logging.error(
                "Getting amount for %s failed due to a network error: %s", symbol, e
            )
            raise TryAgain
        except ccxt.ExchangeError as e:
            logging.error(
                "Getting amount for %s failed due to an exchange error: %s", symbol, e
            )
            raise TryAgain
        except ccxt.BaseError as e:
            logging.error("Getting amount for %s failed due to an error: %s", symbol, e)
            raise TryAgain
        except Exception as e:
            # Broad catch to retry on unexpected exchange errors.
            logging.error("Getting amount for %s failed with: %s", symbol, e)
            raise TryAgain

        return amount

    def __precision_step_for_amount(self, amount_str: str) -> float:
        """Infer amount step from a precision-formatted string."""
        if "." not in amount_str:
            return 1.0

        decimals = amount_str.split(".", 1)[1]
        decimals = decimals.rstrip("0")
        if not decimals:
            return 1.0
        return 10 ** (-len(decimals))

    def __reduce_amount_by_step(
        self, symbol: str, current_amount: float, steps: int
    ) -> float:
        """Reduce amount by precision step and return exchange-formatted value."""
        formatted = self.exchange.amount_to_precision(symbol, current_amount)
        step = self.__precision_step_for_amount(formatted)
        reduced = max(0.0, float(formatted) - (step * max(1, steps)))
        return float(self.exchange.amount_to_precision(symbol, reduced))

    @staticmethod
    def __safe_float(value: Any) -> float | None:
        """Convert a value to float when possible."""
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def __get_min_notional_for_symbol(
        self, symbol: str, *, is_market_order: bool
    ) -> float | None:
        """Resolve minimum notional for a symbol from CCXT market metadata."""
        if self.exchange is None:
            return None

        min_values: list[float] = []
        try:
            market = self.exchange.market(symbol)
        except (ccxt.BaseError, TypeError, ValueError):
            return None
        if not isinstance(market, dict):
            return None

        limits = market.get("limits")
        if isinstance(limits, dict):
            cost_limits = limits.get("cost")
            if isinstance(cost_limits, dict):
                min_cost = self.__safe_float(cost_limits.get("min"))
                if min_cost and min_cost > 0:
                    min_values.append(min_cost)

        info = market.get("info")
        if isinstance(info, dict):
            filters = info.get("filters")
            if isinstance(filters, list):
                for filter_data in filters:
                    if not isinstance(filter_data, dict):
                        continue
                    filter_type = str(filter_data.get("filterType", "")).upper()
                    min_notional = self.__safe_float(filter_data.get("minNotional"))
                    if not min_notional or min_notional <= 0:
                        continue

                    if filter_type == "MIN_NOTIONAL":
                        if (
                            is_market_order
                            and str(filter_data.get("applyToMarket", "true")).lower()
                            == "false"
                        ):
                            continue
                        min_values.append(min_notional)
                    elif filter_type == "NOTIONAL":
                        if (
                            is_market_order
                            and str(filter_data.get("applyMinToMarket", "true")).lower()
                            == "false"
                        ):
                            continue
                        min_values.append(min_notional)

        if not min_values:
            return None
        return max(min_values)

    def __is_notional_below_minimum(
        self, symbol: str, amount: float, price: float, *, is_market_order: bool
    ) -> tuple[bool, float | None, float]:
        """Check whether an order notional is below exchange minimum."""
        estimated_notional = max(0.0, float(amount)) * max(0.0, float(price))
        min_notional = self.__get_min_notional_for_symbol(
            symbol, is_market_order=is_market_order
        )
        if min_notional is None:
            return False, None, estimated_notional
        return estimated_notional < min_notional, min_notional, estimated_notional

    def __resolve_required_buy_quote(self, order: dict[str, Any]) -> float | None:
        """Return required quote amount for a buy order."""
        requested_quote = self.__safe_float(order.get("ordersize"))
        required_quote = (
            requested_quote if requested_quote and requested_quote > 0 else None
        )

        amount = self.__safe_float(order.get("amount"))
        price = self.__safe_float(order.get("price"))
        if amount is not None and amount > 0 and price is not None and price > 0:
            estimated_quote = amount * price
            if required_quote is None:
                required_quote = estimated_quote
            else:
                required_quote = max(required_quote, estimated_quote)

        if required_quote is None or required_quote <= 0:
            return None
        return float(required_quote)

    @staticmethod
    def __extract_free_amount(balance: dict[str, Any], asset: str) -> float | None:
        """Extract free amount for an asset from CCXT balance payload."""
        free_amount = None
        asset_info = balance.get(asset)
        if isinstance(asset_info, dict):
            free_amount = asset_info.get("free")

        if free_amount is None:
            free_map = balance.get("free")
            if isinstance(free_map, dict):
                free_amount = free_map.get(asset)

        if free_amount is None:
            return None

        try:
            return float(free_amount)
        except (TypeError, ValueError):
            return None

    async def __get_balance_snapshot(
        self, force_refresh: bool = False
    ) -> dict[str, Any] | None:
        """Return cached exchange balance snapshot with short TTL."""
        if self.exchange is None:
            return None

        now = asyncio.get_running_loop().time()
        if (
            not force_refresh
            and self._balance_cache is not None
            and now - self._balance_cache_ts < self.BALANCE_CACHE_TTL_SECONDS
        ):
            return self._balance_cache

        async with self._balance_lock:
            now = asyncio.get_running_loop().time()
            if (
                not force_refresh
                and self._balance_cache is not None
                and now - self._balance_cache_ts < self.BALANCE_CACHE_TTL_SECONDS
            ):
                return self._balance_cache

            balance = await self.exchange.fetch_balance()
            self._balance_cache = balance
            self._balance_cache_ts = now
            return balance

    async def __get_available_base_amount(
        self, symbol: str, force_refresh: bool = False
    ) -> float | None:
        """Return currently available base asset amount for a symbol."""
        resolved_symbol = self.__resolve_symbol(symbol)
        if resolved_symbol is None:
            return None

        base_asset = resolved_symbol.split("/")[0].split(":")[0]
        try:
            balance = await self.__get_balance_snapshot(force_refresh=force_refresh)
        except (ccxt.BaseError, RuntimeError, OSError) as exc:
            logging.warning("Fetching balance for %s failed: %s", resolved_symbol, exc)
            return None

        if balance is None:
            return None
        free_amount = self.__extract_free_amount(balance, base_asset)
        if free_amount is None:
            return None

        try:
            return float(
                self.exchange.amount_to_precision(resolved_symbol, free_amount)
            )
        except (ccxt.BaseError, TypeError, ValueError):
            return free_amount

    async def __log_remaining_sell_dust(self, symbol: str) -> None:
        """Log remaining base-asset balance after sell execution.

        Small leftovers are common due to precision and minimum-order constraints.
        This method keeps the behavior explicit and observable without adding
        exchange-specific convert/dust trading logic.
        """
        remaining_amount = await self.__get_available_base_amount(symbol)
        if remaining_amount is None:
            return
        if remaining_amount <= 0:
            return
        logging.info(
            "Remaining base amount for %s after sell execution: %s",
            symbol,
            remaining_amount,
        )

    async def get_free_quote_balance(
        self, config: dict[str, Any], symbol: str, force_refresh: bool = False
    ) -> float | None:
        """Return currently available quote asset balance for a symbol."""
        await self.__ensure_exchange(config)
        await self.__ensure_markets_loaded()

        resolved_symbol = self.__resolve_symbol(symbol)
        if resolved_symbol is None:
            return None

        quote_asset = resolved_symbol.split("/")[1].split(":")[0]
        try:
            balance = await self.__get_balance_snapshot(force_refresh=force_refresh)
        except (ccxt.BaseError, RuntimeError, OSError) as exc:
            logging.warning("Fetching quote balance for %s failed: %s", symbol, exc)
            return None

        if balance is None:
            return None
        return self.__extract_free_amount(balance, quote_asset)

    async def __preflight_buy_funds(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Check quote balance before placing a buy order."""
        self._last_buy_precheck_result = None

        symbol = str(order.get("symbol") or "")
        resolved_symbol = self.__resolve_symbol(symbol)
        if resolved_symbol is None:
            self._last_buy_precheck_result = {
                "ok": False,
                "reason": "symbol_not_found",
                "symbol": symbol,
            }
            return False

        required_quote = self.__resolve_required_buy_quote(order)
        if required_quote is None:
            self._last_buy_precheck_result = {
                "ok": False,
                "reason": "invalid_required_quote",
                "symbol": resolved_symbol,
            }
            return False

        buffer_pct = self.__safe_float(config.get("buy_fund_buffer_pct"))
        if buffer_pct is None or buffer_pct < 0:
            buffer_pct = 0.0
        required_with_buffer = required_quote * (1 + buffer_pct)

        available_quote = await self.get_free_quote_balance(
            config=config,
            symbol=resolved_symbol,
            force_refresh=True,
        )
        if available_quote is None:
            self._last_buy_precheck_result = {
                "ok": False,
                "reason": "balance_unavailable",
                "symbol": resolved_symbol,
                "required_quote": round(required_with_buffer, 8),
                "available_quote": None,
                "buffer_pct": round(buffer_pct, 6),
            }
            return False

        if available_quote + 1e-12 < required_with_buffer:
            self._last_buy_precheck_result = {
                "ok": False,
                "reason": "insufficient_quote_balance",
                "symbol": resolved_symbol,
                "required_quote": round(required_with_buffer, 8),
                "available_quote": round(float(available_quote), 8),
                "buffer_pct": round(buffer_pct, 6),
            }
            return False

        self._last_buy_precheck_result = {
            "ok": True,
            "reason": "ok",
            "symbol": resolved_symbol,
            "required_quote": round(required_with_buffer, 8),
            "available_quote": round(float(available_quote), 8),
            "buffer_pct": round(buffer_pct, 6),
        }
        return True

    def get_last_buy_precheck_result(self) -> dict[str, Any] | None:
        """Return metadata from the most recent buy funds pre-check."""
        return self._last_buy_precheck_result

    async def get_free_balance_for_asset(
        self, config: dict[str, Any], asset: str
    ) -> float | None:
        """Return currently available balance for an asset symbol (e.g. USDC)."""
        await self.__ensure_exchange(config)
        if self.exchange is None:
            return None

        asset_symbol = str(asset or "").strip().upper()
        if not asset_symbol:
            return None

        try:
            balance = await self.__get_balance_snapshot()
        except (ccxt.BaseError, RuntimeError, OSError) as exc:
            logging.warning(
                "Fetching free balance for %s failed: %s", asset_symbol, exc
            )
            return None

        if balance is None:
            return None
        return self.__extract_free_amount(balance, asset_symbol)

    async def __resolve_sell_amount(
        self, symbol: str, requested_amount: float
    ) -> tuple[str, float] | None:
        """Resolve sell amount capped by current free balance."""
        resolved_symbol = self.__resolve_symbol(symbol)
        if resolved_symbol is None:
            return None

        target_amount = max(0.0, float(requested_amount))
        available_amount = await self.__get_available_base_amount(
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

    async def __init_exchange(self, config: dict[str, Any]) -> Any:
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
                logging.info(
                    "Using custom exchange hostname '%s' for exchange '%s'.",
                    options["hostname"],
                    config.get("exchange"),
                )
            if config.get("dry_run", True):
                try:
                    exchange.enableDemoTrading(True)
                    logging.info(
                        "Enabled CCXT demo trading for exchange '%s'.",
                        config.get("exchange"),
                    )
                except (AttributeError, NotImplementedError, ccxt.BaseError) as exc:
                    raise ValueError(
                        "Dry run requires CCXT enableDemoTrading support, but "
                        f"'{config.get('exchange')}' could not enable demo trading."
                    ) from exc
            # exchange.set_sandbox_mode(config.get("sandbox", False))
            exchange.enableRateLimit = True

        return exchange

    async def create_spot_market_buy(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Create a spot market buy order."""
        await self.__ensure_exchange(config)
        await self.__ensure_markets_loaded()
        self.config = config
        self._last_buy_precheck_result = None
        order["amount"] = await self.__get_amount_from_symbol(
            order["ordersize"], order["symbol"]
        )
        order["price"] = await self.__get_price_for_symbol(order["symbol"])
        if not order["price"] or not order["amount"] or float(order["amount"]) <= 0:
            logging.error(
                "Skipping buy for %s: invalid price/amount (price=%s, amount=%s).",
                order.get("symbol"),
                order.get("price"),
                order.get("amount"),
            )
            return None
        if not await self.__preflight_buy_funds(order, config):
            precheck = self._last_buy_precheck_result or {}
            logging.warning(
                "Skipping buy for %s: funds check failed (%s). required=%s available=%s",
                order.get("symbol"),
                precheck.get("reason", "unknown"),
                precheck.get("required_quote"),
                precheck.get("available_quote"),
            )
            return None
        order = await self.__execute_market_buy(order)

        if order:
            logging.info("Opened trade: %s", order)

            order_status = await self.__parse_order_status(order)
            order.update(order_status)
            if not order.get("amount") or float(order["amount"]) <= 0:
                logging.error(
                    "Buy order for %s returned zero amount. Skipping trade creation.",
                    order.get("symbol"),
                )
                return None
            order["precision"] = await self.__get_precision_for_symbol(
                order_status["symbol"]
            )
            resolved_symbol = self.__resolve_symbol(order_status["symbol"])
            if resolved_symbol is None:
                logging.error(
                    "Cannot finalize buy for %s: symbol not found.",
                    order_status["symbol"],
                )
                return None
            order["amount"] = float(order_status["amount"])
            order["amount_fee"] = 0.0
            order["fees"] = 0.0

            # Keep fee rate for statistics/profit calculation.
            if self.config.get("dry_run", True):
                try:
                    order["fees"] = self.__get_demo_taker_fee_for_symbol(
                        order_status["symbol"]
                    )
                except (ValueError, TypeError, ccxt.BaseError) as e:
                    logging.warning(
                        "Demo mode fee lookup for %s failed (%s). "
                        "Using taker fee 0.0 as fallback.",
                        order_status["symbol"],
                        e,
                    )
                    order["fees"] = 0.0
            else:
                try:
                    fees = await self.exchange.fetch_trading_fee(
                        symbol=order_status["symbol"]
                    )
                    order["fees"] = float(fees.get("taker", 0.0))
                except (ccxt.BaseError, TypeError, ValueError) as e:
                    # Broad catch to avoid failing a filled order due fee-rate fetch only.
                    logging.warning(
                        "Fetching fee rate for pair %s failed (%s). Using 0.0 fallback.",
                        order["symbol"],
                        e,
                    )
                    order["fees"] = 0.0

            # Subtract base-asset fee from sellable amount when fee token mode is disabled.
            if not self.config.get("fee_deduction", False):
                order["amount_fee"] = float(order_status.get("base_fee") or 0.0)
                net_amount = max(
                    0.0, float(order_status["amount"]) - order["amount_fee"]
                )
                # Keep full net amount precision here to avoid large relative losses
                # on small orders. Sell path already applies exchange precision.
                order["amount"] = float(net_amount)

                logging.debug(
                    "Fee Deduction not active. Real amount %s, deducted amount %s, base fee %s",
                    order_status["amount"],
                    order["amount"],
                    order["amount_fee"],
                )

            logging.debug(order)

            return order

    async def __execute_market_buy(
        self, order: dict[str, Any]
    ) -> dict[str, Any] | None:
        try:
            logging.info("Try to buy %s %s", order["amount"], order["symbol"])
            parameter = {}
            trade = await self.exchange.create_order(
                order["symbol"],
                order["ordertype"],
                order["side"],
                order["amount"],
                order["price"],
                parameter,
            )
            order.update(trade)
            return order
        except ccxt.ExchangeError as e:
            logging.error(
                "Buying pair %s failed due to an exchange error: %s", order["symbol"], e
            )
            return None
        except ccxt.NetworkError as e:
            logging.error(
                "Buying pair %s failed due to an network error: %s", order["symbol"], e
            )
            return None
        except ccxt.BaseError as e:
            logging.error(
                "Buying pair %s failed due to an error: %s", order["symbol"], e
            )
            return None
        except (TypeError, ValueError, RuntimeError, KeyError) as e:
            # Broad catch to surface unexpected exchange errors.
            logging.error("Buying pair %s failed with: %s", order["symbol"], e)
            return None

    async def create_spot_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Create a sell order using configured execution mode."""
        sell_order_type = str(config.get("sell_order_type", "market")).lower()
        if sell_order_type == "limit":
            order_status = await self.create_spot_limit_sell(order, config)
            if order_status:
                if order_status.get("requires_market_fallback"):
                    if not bool(order_status.get("limit_cancel_confirmed", False)):
                        logging.error(
                            "Skipping market fallback for %s because limit cancel "
                            "was not confirmed.",
                            order.get("symbol"),
                        )
                        return None
                    if not bool(config.get("limit_sell_fallback_to_market", True)):
                        logging.info(
                            "Limit sell for %s partially filled, but market fallback is disabled.",
                            order.get("symbol"),
                        )
                        return self.__build_partial_sell_status(
                            symbol=str(order_status.get("symbol", order.get("symbol"))),
                            partial_amount=float(
                                order_status.get("partial_filled_amount") or 0.0
                            ),
                            partial_avg_price=float(
                                order_status.get("partial_avg_price") or 0.0
                            ),
                            remaining_amount=float(
                                order_status.get("remaining_amount") or 0.0
                            ),
                        )
                    if not await self.__can_fallback_to_market_sell(order, config):
                        return self.__build_partial_sell_status(
                            symbol=str(order_status.get("symbol", order.get("symbol"))),
                            partial_amount=float(
                                order_status.get("partial_filled_amount") or 0.0
                            ),
                            partial_avg_price=float(
                                order_status.get("partial_avg_price") or 0.0
                            ),
                            remaining_amount=float(
                                order_status.get("remaining_amount") or 0.0
                            ),
                        )
                    logging.info(
                        "Limit sell for %s was not filled. Falling back to market sell.",
                        order.get("symbol"),
                    )
                    remaining_order = dict(order)
                    remaining_order["total_amount"] = float(
                        order_status.get("remaining_amount") or 0.0
                    )
                    market_status = await self.create_spot_market_sell(
                        remaining_order, config
                    )
                    if not market_status:
                        return None
                    partial_amount = float(
                        order_status.get("partial_filled_amount") or 0.0
                    )
                    partial_price = float(order_status.get("partial_avg_price") or 0.0)
                    if market_status.get("type") == "partial_sell":
                        market_partial_amount = float(
                            market_status.get("partial_filled_amount") or 0.0
                        )
                        market_partial_price = float(
                            market_status.get("partial_avg_price") or 0.0
                        )
                        combined_partial_amount = partial_amount + market_partial_amount
                        combined_proceeds = (
                            partial_amount * partial_price
                            + market_partial_amount * market_partial_price
                        )
                        combined_partial_price = (
                            combined_proceeds / combined_partial_amount
                            if combined_partial_amount > 0
                            else 0.0
                        )
                        return self.__build_partial_sell_status(
                            symbol=str(order_status.get("symbol", order.get("symbol"))),
                            partial_amount=combined_partial_amount,
                            partial_avg_price=combined_partial_price,
                            remaining_amount=float(
                                market_status.get("remaining_amount") or 0.0
                            ),
                            unsellable=bool(market_status.get("unsellable", False)),
                            unsellable_reason=(
                                str(market_status.get("unsellable_reason"))
                                if market_status.get("unsellable_reason")
                                else None
                            ),
                            unsellable_min_notional=(
                                float(market_status.get("unsellable_min_notional"))
                                if market_status.get("unsellable_min_notional")
                                is not None
                                else None
                            ),
                            unsellable_estimated_notional=(
                                float(
                                    market_status.get("unsellable_estimated_notional")
                                )
                                if market_status.get("unsellable_estimated_notional")
                                is not None
                                else None
                            ),
                        )
                    market_amount = float(market_status.get("total_amount") or 0.0)
                    market_price = float(market_status.get("price") or 0.0)
                    combined_amount = partial_amount + market_amount
                    if combined_amount <= 0:
                        return market_status

                    total_cost = float(order.get("total_cost") or 0.0)
                    proceeds = (partial_amount * partial_price) + (
                        market_amount * market_price
                    )
                    avg_sell_price = proceeds / combined_amount
                    avg_buy_price = (
                        total_cost / combined_amount if combined_amount > 0 else 0.0
                    )
                    profit = proceeds - total_cost
                    profit_percent = (
                        ((avg_sell_price - avg_buy_price) / avg_buy_price) * 100
                        if avg_buy_price > 0
                        else 0.0
                    )
                    market_status["total_amount"] = combined_amount
                    market_status["price"] = avg_sell_price
                    market_status["tp_price"] = avg_sell_price
                    market_status["avg_price"] = avg_buy_price
                    market_status["profit"] = profit
                    market_status["profit_percent"] = profit_percent
                    return market_status
                return order_status

            if bool(config.get("limit_sell_fallback_to_market", True)):
                if order.get("_limit_cancel_confirmed") is False:
                    logging.error(
                        "Skipping market fallback for %s because limit cancel "
                        "was not confirmed.",
                        order.get("symbol"),
                    )
                    return None
                if not await self.__can_fallback_to_market_sell(order, config):
                    return None
                logging.info(
                    "Limit sell for %s was not filled. Falling back to market sell.",
                    order.get("symbol"),
                )
                return await self.create_spot_market_sell(order, config)

            logging.info(
                "Limit sell for %s was not filled. Market fallback is disabled.",
                order.get("symbol"),
            )
            return None

        return await self.create_spot_market_sell(order, config)

    async def __can_fallback_to_market_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Check whether market fallback is allowed after limit timeout."""
        if not bool(config.get("limit_sell_fallback_tp_guard", True)):
            return True

        fallback_min_price = order.get("fallback_min_price")
        if fallback_min_price in (None, False):
            return True

        try:
            min_price = float(fallback_min_price)
        except (TypeError, ValueError):
            return True

        try:
            current_price = float(await self.__get_price_for_symbol(order["symbol"]))
        except (ccxt.BaseError, RuntimeError, TypeError, ValueError) as exc:
            logging.warning(
                "Skipping market fallback for %s: could not fetch current price (%s).",
                order.get("symbol"),
                exc,
            )
            return False

        if current_price < min_price:
            logging.info(
                "Skipping market fallback for %s: current price %.10f is below "
                "minimum fallback price %.10f.",
                order.get("symbol"),
                current_price,
                min_price,
            )
            return False

        return True

    async def __build_sell_order_status(
        self, order: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Build normalized sell order status for closed trade processing."""
        order_status = await self.__parse_order_status(order)
        if not order_status.get("total_amount"):
            logging.error(
                "Sell order for %s returned empty amount.", order.get("symbol")
            )
            return None

        order_status["type"] = "sold_check"
        order_status["sell"] = True
        order_status["total_cost"] = order["total_cost"]
        order_status["actual_pnl"] = order["actual_pnl"]
        order_status["avg_price"] = (
            order_status["total_cost"] / order_status["total_amount"]
        )
        order_status["tp_price"] = order_status["price"]
        order_status["profit"] = (
            order_status["price"] * order_status["total_amount"]
            - order_status["total_cost"]
        )
        order_status["profit_percent"] = (
            (order_status["price"] - order_status["avg_price"])
            / order_status["avg_price"]
        ) * 100
        return order_status

    def __build_partial_sell_status(
        self,
        symbol: str,
        partial_amount: float,
        partial_avg_price: float,
        remaining_amount: float,
        unsellable: bool = False,
        unsellable_reason: str | None = None,
        unsellable_min_notional: float | None = None,
        unsellable_estimated_notional: float | None = None,
    ) -> dict[str, Any]:
        """Build a partial execution status for deferred close accounting."""
        return {
            "type": "partial_sell",
            "symbol": symbol,
            "partial_filled_amount": float(partial_amount),
            "partial_avg_price": float(partial_avg_price),
            "partial_proceeds": float(partial_amount * partial_avg_price),
            "remaining_amount": float(remaining_amount),
            "unsellable": bool(unsellable),
            "unsellable_reason": unsellable_reason,
            "unsellable_min_notional": (
                float(unsellable_min_notional)
                if unsellable_min_notional is not None
                else None
            ),
            "unsellable_estimated_notional": (
                float(unsellable_estimated_notional)
                if unsellable_estimated_notional is not None
                else None
            ),
        }

    async def __wait_for_limit_sell_fill(
        self, symbol: str, order_id: str, timeout_seconds: int
    ) -> dict[str, Any] | None:
        """Poll an order until it is closed or times out."""
        start_time = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start_time) < timeout_seconds:
            try:
                status = await self.exchange.fetch_order(order_id, symbol)
                order_status = str(status.get("status", "")).lower()
                filled = float(status.get("filled") or 0.0)
                amount = float(status.get("amount") or 0.0)

                if order_status in {"closed", "filled"} or (
                    amount > 0 and filled >= amount
                ):
                    return status

                if order_status in {"canceled", "cancelled", "rejected", "expired"}:
                    return None
            except ccxt.NetworkError as exc:
                logging.warning(
                    "Polling limit sell status failed due to network error: %s", exc
                )
            except ccxt.ExchangeError as exc:
                logging.warning(
                    "Polling limit sell status failed due to exchange error: %s", exc
                )
            except ccxt.BaseError as exc:
                logging.warning("Polling limit sell status failed: %s", exc)
            except (TypeError, ValueError, RuntimeError, KeyError) as exc:
                logging.warning("Polling limit sell status failed: %s", exc)

            await asyncio.sleep(1)

        return None

    async def __cancel_order_safe(self, symbol: str, order_id: str) -> None:
        """Cancel an order and only log failures."""
        try:
            await self.exchange.cancel_order(order_id, symbol)
        except (ccxt.BaseError, RuntimeError, TypeError, ValueError) as exc:
            logging.warning(
                "Cancel order %s for %s failed or order is already closed: %s",
                order_id,
                symbol,
                exc,
            )

    async def __cancel_order_and_confirm(self, symbol: str, order_id: str) -> bool:
        """Cancel an order and confirm it is no longer open."""
        await self.__cancel_order_safe(symbol, order_id)

        for _ in range(5):
            try:
                latest = await self.exchange.fetch_order(order_id, symbol)
                order_status = str(latest.get("status", "")).lower()
                if order_status in {"closed", "filled", "canceled", "cancelled"}:
                    return True
            except (ccxt.BaseError, RuntimeError, TypeError, ValueError) as exc:
                logging.warning(
                    "Could not verify cancel status for order %s on %s: %s",
                    order_id,
                    symbol,
                    exc,
                )
            await asyncio.sleep(0.5)

        return False

    async def create_spot_limit_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Create a spot limit sell order and wait for fill."""
        await self.__ensure_exchange(config)
        await self.__ensure_markets_loaded()
        self.config = config

        resolved_symbol = self.__resolve_symbol(order["symbol"])
        if resolved_symbol is None:
            logging.error(
                "Cannot place limit sell. Symbol not found: %s", order["symbol"]
            )
            return None

        sell_amount = await self.__resolve_sell_amount(
            resolved_symbol, float(order["total_amount"])
        )
        if sell_amount is None:
            logging.error(
                "Skipping limit sell for %s: no available amount to sell.",
                resolved_symbol,
            )
            return None
        resolved_symbol, amount_value = sell_amount
        amount = self.exchange.amount_to_precision(resolved_symbol, amount_value)

        limit_price = await self.__resolve_limit_sell_price(order, resolved_symbol)
        limit_price_value = float(limit_price)
        below_min_notional, min_notional, estimated_notional = (
            self.__is_notional_below_minimum(
                resolved_symbol,
                amount_value,
                limit_price_value,
                is_market_order=False,
            )
        )
        if below_min_notional:
            logging.info(
                "Skipping limit sell for %s: estimated notional %.8f is below "
                "minimum %.8f. Trying market fallback if enabled.",
                resolved_symbol,
                estimated_notional,
                float(min_notional or 0.0),
            )
            return {
                "requires_market_fallback": True,
                "limit_cancel_confirmed": True,
                "symbol": resolved_symbol,
                "remaining_amount": float(amount_value),
                "partial_filled_amount": 0.0,
                "partial_avg_price": 0.0,
            }

        logging.info(
            "Placing limit sell for %s amount=%s price=%s",
            resolved_symbol,
            amount,
            limit_price,
        )
        trade = await self.__execute_limit_sell(
            resolved_symbol, amount, limit_price, order
        )
        if not trade:
            return None

        sell_order = dict(order)
        sell_order.update(trade)
        sell_order["symbol"] = resolved_symbol
        sell_order["total_amount"] = float(amount_value)
        if not sell_order.get("id"):
            logging.error("Limit sell for %s returned no order id.", resolved_symbol)
            return None

        return await self.__handle_limit_sell_fill(
            sell_order, resolved_symbol, config, order
        )

    async def __resolve_limit_sell_price(
        self, order: dict[str, Any], resolved_symbol: str
    ) -> str:
        current_price = order.get("current_price")
        if current_price and float(current_price) > 0:
            return self.exchange.price_to_precision(
                resolved_symbol, float(current_price)
            )
        else:
            logging.debug(
                "Limit sell for %s has no current_price payload. "
                "Fetching live ticker price.",
                resolved_symbol,
            )
            live_price = await self.__get_price_for_symbol(resolved_symbol)
            return self.exchange.price_to_precision(resolved_symbol, float(live_price))

    async def __execute_limit_sell(
        self, resolved_symbol: str, amount: str, limit_price: str, order: dict[str, Any]
    ) -> dict[str, Any] | None:
        try:
            parameter = {}
            return await self.exchange.create_order(
                resolved_symbol,
                "limit",
                "sell",
                amount,
                limit_price,
                parameter,
            )
        except ccxt.ExchangeError as exc:
            logging.error(
                "Limit sell for %s failed due to an exchange error: %s",
                order["symbol"],
                exc,
            )
            return None
        except ccxt.NetworkError as exc:
            logging.error(
                "Limit sell for %s failed due to a network error: %s",
                order["symbol"],
                exc,
            )
            return None
        except ccxt.BaseError as exc:
            logging.error(
                "Limit sell for %s failed due to an error: %s", order["symbol"], exc
            )
            return None
        except (TypeError, ValueError, RuntimeError, KeyError) as exc:
            logging.error("Limit sell for %s failed with: %s", order["symbol"], exc)
            return None

    async def __handle_limit_sell_fill(
        self,
        sell_order: dict[str, Any],
        resolved_symbol: str,
        config: dict[str, Any],
        original_order: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            timeout_seconds = max(1, int(config.get("limit_sell_timeout_sec", 60)))
        except (TypeError, ValueError):
            timeout_seconds = 60
        filled_order = await self.__wait_for_limit_sell_fill(
            resolved_symbol, str(sell_order["id"]), timeout_seconds
        )
        if not filled_order:
            latest_order_status = None
            try:
                latest_order_status = await self.exchange.fetch_order(
                    str(sell_order["id"]), resolved_symbol
                )
            except (ccxt.BaseError, RuntimeError, TypeError, ValueError):
                latest_order_status = None

            if latest_order_status:
                filled_amount = float(latest_order_status.get("filled") or 0.0)
                remaining_amount = float(latest_order_status.get("remaining") or 0.0)
                if filled_amount > 0:
                    logging.info(
                        "Limit sell for %s partially filled before timeout. "
                        "filled=%s remaining=%s",
                        resolved_symbol,
                        filled_amount,
                        remaining_amount,
                    )
                    if remaining_amount <= 0:
                        sell_order.update(latest_order_status)
                        return await self.__build_sell_order_status(sell_order)
                    cancel_confirmed = await self.__cancel_order_and_confirm(
                        resolved_symbol, str(sell_order["id"])
                    )
                    if not cancel_confirmed:
                        logging.error(
                            "Limit order %s for %s partially filled but could not be "
                            "confirmed canceled. Skipping market fallback to avoid "
                            "double-selling.",
                            sell_order["id"],
                            resolved_symbol,
                        )
                        return None

                    partial_fill_status = await self.__parse_order_status(sell_order)
                    return {
                        "requires_market_fallback": True,
                        "limit_cancel_confirmed": True,
                        "symbol": resolved_symbol,
                        "remaining_amount": remaining_amount,
                        "partial_filled_amount": float(
                            partial_fill_status.get("total_amount") or filled_amount
                        ),
                        "partial_avg_price": float(
                            partial_fill_status.get("price")
                            or latest_order_status.get("average")
                            or latest_order_status.get("price")
                            or 0.0
                        ),
                    }

            logging.info(
                "Limit sell for %s was not filled within %s seconds.",
                resolved_symbol,
                timeout_seconds,
            )
            cancel_confirmed = await self.__cancel_order_and_confirm(
                resolved_symbol, str(sell_order["id"])
            )
            if not cancel_confirmed:
                logging.error(
                    "Limit order %s for %s was not filled but could not be "
                    "confirmed canceled. Skipping market fallback.",
                    sell_order["id"],
                    resolved_symbol,
                )
                original_order["_limit_cancel_confirmed"] = False
            else:
                original_order["_limit_cancel_confirmed"] = True
            return None

        sell_order.update(filled_order)
        logging.info("Limit sell for %s filled.", resolved_symbol)
        return await self.__build_sell_order_status(sell_order)

    @retry(wait=wait_fixed(1), stop=stop_after_attempt(200))
    async def create_spot_market_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Create a spot market sell order."""
        await self.__ensure_exchange(config)
        await self.__ensure_markets_loaded()
        self.config = config
        resolved_symbol = self.__resolve_symbol(order["symbol"])
        if resolved_symbol is None:
            logging.error("Selling pair %s failed: symbol not found.", order["symbol"])
            return None
        try:
            requested_amount = float(order["total_amount"])
            sell_amount = await self.__resolve_sell_amount(
                resolved_symbol, requested_amount
            )
            if sell_amount is None:
                logging.error(
                    "Skipping market sell for %s: no available amount to sell.",
                    resolved_symbol,
                )
                return None
            resolved_symbol, available_amount = sell_amount
            order["total_amount"] = available_amount
            if available_amount < requested_amount:
                logging.info(
                    "Reducing market sell for %s to available balance: requested=%s available=%s",
                    resolved_symbol,
                    requested_amount,
                    available_amount,
                )

            # Implement sell safeguard, if we cannot sell full amount
            current_amount = float(order["total_amount"])
            if Exchange.sell_retry_count > 0:
                reduced_amount = self.__reduce_amount_by_step(
                    resolved_symbol, current_amount, Exchange.sell_retry_count
                )
                order["total_amount"] = reduced_amount
                logging.info("Reducing amount for sell to: %s", order["total_amount"])
            else:
                order["total_amount"] = float(
                    self.exchange.amount_to_precision(resolved_symbol, current_amount)
                )

            notional_price_value = self.__safe_float(order.get("current_price"))
            if notional_price_value is None or notional_price_value <= 0:
                try:
                    notional_price_value = float(
                        await self.__get_price_for_symbol(resolved_symbol)
                    )
                except (ccxt.BaseError, RuntimeError, TypeError, ValueError):
                    notional_price_value = None

            if notional_price_value and notional_price_value > 0:
                below_min_notional, min_notional, estimated_notional = (
                    self.__is_notional_below_minimum(
                        resolved_symbol,
                        float(order["total_amount"]),
                        notional_price_value,
                        is_market_order=True,
                    )
                )
                if below_min_notional:
                    logging.info(
                        "Skipping market sell for %s: estimated notional %.8f is "
                        "below minimum %.8f (amount=%s, price=%s).",
                        resolved_symbol,
                        estimated_notional,
                        float(min_notional or 0.0),
                        order["total_amount"],
                        notional_price_value,
                    )
                    return self.__build_partial_sell_status(
                        symbol=resolved_symbol,
                        partial_amount=0.0,
                        partial_avg_price=0.0,
                        remaining_amount=float(order["total_amount"]),
                        unsellable=True,
                        unsellable_reason="minimum_notional",
                        unsellable_min_notional=float(min_notional or 0.0),
                        unsellable_estimated_notional=float(estimated_notional),
                    )

            trade = await self.exchange.create_market_sell_order(
                resolved_symbol, order["total_amount"]
            )
            order.update(trade)
            await self.__log_remaining_sell_dust(resolved_symbol)
        except ccxt.ExchangeError as e:
            if "insufficient balance" in str(e):
                logging.error(
                    "Trying to sell %s of pair %s failed due insufficient balance.",
                    order["total_amount"],
                    order["symbol"],
                )
                Exchange.sell_retry_count += 1
                raise TryAgain
            if "filter failure: notional" in str(e).lower():
                logging.info(
                    "Skipping market sell for %s due NOTIONAL filter failure. "
                    "Keeping position open for a later retry.",
                    resolved_symbol,
                )
                return self.__build_partial_sell_status(
                    symbol=resolved_symbol,
                    partial_amount=0.0,
                    partial_avg_price=0.0,
                    remaining_amount=float(order.get("total_amount") or 0.0),
                    unsellable=True,
                    unsellable_reason="minimum_notional",
                )
            else:
                logging.error(
                    "Selling pair %s failed due to an exchange error: %s",
                    order["symbol"],
                    e,
                )
                order = None
        except ccxt.NetworkError as e:
            logging.error(
                "Selling pair %s failed due to an network error: %s", order["symbol"], e
            )
            order = None
        except ccxt.BaseError as e:
            logging.error(
                "Selling pair %s failed due to an error: %s", order["symbol"], e
            )
            order = None
        except (TypeError, ValueError, RuntimeError, KeyError) as e:
            # Broad catch to surface unexpected exchange errors.
            logging.error("Selling pair %s failed with: %s", order["symbol"], e)
            order = None

        if order:
            if order.get("type") == "partial_sell":
                return order
            logging.info(
                "Sold %s %s on Exchange.", order["total_amount"], order["symbol"]
            )
            Exchange.sell_retry_count = 0
            return await self.__build_sell_order_status(order)
