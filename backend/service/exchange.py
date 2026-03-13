"""Exchange service for CCXT async operations."""

import asyncio
from typing import Any

import ccxt.async_support as ccxt
import helper
from service.exchange_balance_manager import ExchangeBalanceManager
from service.exchange_buy_manager import ExchangeBuyManager
from service.exchange_client_manager import ExchangeClientManager
from service.exchange_helpers import (
    aggregate_matched_trades,
    is_matching_order_id,
    precision_step_for_amount,
)
from service.exchange_limit_order_manager import ExchangeLimitOrderManager
from service.exchange_limit_sell_manager import ExchangeLimitSellManager
from service.exchange_risk import (
    build_buy_precheck_result,
    get_min_notional_for_market,
    is_notional_below_minimum,
    normalize_buy_buffer_pct,
    resolve_required_buy_quote,
)
from service.exchange_sell_manager import ExchangeSellManager
from service.exchange_sell_status import finalize_sell_order_status
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
        self.config = None
        self.status = True
        Exchange.sell_retry_count = 0
        self._last_buy_precheck_result: dict[str, Any] | None = None
        self._client_manager = ExchangeClientManager(logging)
        self._balance_manager = ExchangeBalanceManager(
            logger=logging,
            balance_cache_ttl_seconds=self.BALANCE_CACHE_TTL_SECONDS,
            get_exchange=lambda: self.exchange,
            resolve_symbol=self.__resolve_symbol,
        )
        self._buy_manager = ExchangeBuyManager(
            logger=logging,
            get_exchange=lambda: self.exchange,
        )
        self._limit_order_manager = ExchangeLimitOrderManager(
            logger=logging,
            get_exchange=lambda: self.exchange,
        )
        self._sell_manager = ExchangeSellManager(
            logger=logging,
            get_exchange=lambda: self.exchange,
            get_sell_retry_count=lambda: Exchange.sell_retry_count,
            set_sell_retry_count=lambda value: setattr(
                Exchange, "sell_retry_count", value
            ),
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

    async def __close_exchange(self) -> None:
        await self._client_manager.close()
        self._balance_manager.reset()

    async def close(self) -> None:
        """Close the underlying exchange client."""
        await self.__close_exchange()

    async def __ensure_exchange(self, config: dict[str, Any]) -> None:
        changed = await self._client_manager.ensure_exchange(config)
        if changed:
            self._balance_manager.reset()

    async def __ensure_markets_loaded(self) -> None:
        await self._client_manager.ensure_markets_loaded()

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
        """Return the current exchange price for a symbol with exchange precision."""
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
            logging.error("Fetching ticker data failed due to an exchange error: %s", e)
            raise TryAgain
        except ccxt.NetworkError as e:
            logging.error("Fetching ticker data failed due to a network error: %s", e)
            raise TryAgain
        except ccxt.BaseError as e:
            logging.error("Fetching ticker data failed due to an error: %s", e)
            raise TryAgain
        except TryAgain:
            raise
        except (TypeError, ValueError, RuntimeError) as e:
            # Broad catch to retry on unexpected exchange errors.
            logging.error(
                "Fetching ticker data failed with unexpected error type %s: %r",
                type(e).__name__,
                e,
            )
            raise TryAgain

        return result

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    async def __get_precision_for_symbol(self, pair: str) -> Any:
        """Return exchange amount precision for a symbol."""
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
            logging.error("Fetching market data failed with: %s", e)
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
            if is_matching_order_id(order.get("order"), orderid)
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
                    if is_matching_order_id(order.get("order"), orderid)
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
                logging.debug(
                    "Orderlist for %s with orderid: %s: %s",
                    symbol,
                    orderid,
                    matched_orders,
                )
                trade = aggregate_matched_trades(matched_orders, symbol)
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

    def __reduce_amount_by_step(
        self, symbol: str, current_amount: float, steps: int
    ) -> float:
        """Reduce amount by precision step and return exchange-formatted value."""
        formatted = self.exchange.amount_to_precision(symbol, current_amount)
        step = precision_step_for_amount(formatted)
        reduced = max(0.0, float(formatted) - (step * max(1, steps)))
        return float(self.exchange.amount_to_precision(symbol, reduced))

    def __get_min_notional_for_symbol(
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

    def __is_notional_below_minimum(
        self, symbol: str, amount: float, price: float, *, is_market_order: bool
    ) -> tuple[bool, float | None, float]:
        """Check whether an order notional is below exchange minimum."""
        min_notional = self.__get_min_notional_for_symbol(
            symbol, is_market_order=is_market_order
        )
        return is_notional_below_minimum(amount, price, min_notional)

    def __resolve_required_buy_quote(self, order: dict[str, Any]) -> float | None:
        """Return required quote amount for a buy order."""
        return resolve_required_buy_quote(order)

    def __is_limit_sell_notional_below_minimum(
        self,
        symbol: str,
        amount: float,
        price: float,
    ) -> tuple[bool, float | None, float]:
        """Check minimum notional for a limit sell."""
        return self.__is_notional_below_minimum(
            symbol,
            amount,
            price,
            is_market_order=False,
        )

    def __is_market_sell_notional_below_minimum(
        self,
        symbol: str,
        amount: float,
        price: float,
    ) -> tuple[bool, float | None, float]:
        """Check minimum notional for a market sell."""
        return self.__is_notional_below_minimum(
            symbol,
            amount,
            price,
            is_market_order=True,
        )

    async def __get_available_base_amount(
        self, symbol: str, force_refresh: bool = False
    ) -> float | None:
        """Return currently available base asset amount for a symbol."""
        return await self._balance_manager.get_available_base_amount(
            symbol,
            force_refresh=force_refresh,
        )

    async def __log_remaining_sell_dust(self, symbol: str) -> None:
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
        await self.__ensure_exchange(config)
        await self.__ensure_markets_loaded()
        return await self._balance_manager.get_free_quote_balance(
            symbol,
            force_refresh=force_refresh,
        )

    async def __preflight_buy_funds(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Check quote balance before placing a buy order."""
        self._last_buy_precheck_result = None

        symbol = str(order.get("symbol") or "")
        resolved_symbol = self.__resolve_symbol(symbol)
        if resolved_symbol is None:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="symbol_not_found",
                symbol=symbol,
            )
            return False

        required_quote = self.__resolve_required_buy_quote(order)
        if required_quote is None:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="invalid_required_quote",
                symbol=resolved_symbol,
            )
            return False

        buffer_pct = normalize_buy_buffer_pct(config.get("buy_fund_buffer_pct"))
        required_with_buffer = required_quote * (1 + buffer_pct)

        available_quote = await self.get_free_quote_balance(
            config=config,
            symbol=resolved_symbol,
            force_refresh=True,
        )
        if available_quote is None:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="balance_unavailable",
                symbol=resolved_symbol,
                required_quote=required_with_buffer,
                available_quote=None,
                buffer_pct=buffer_pct,
            )
            return False

        if available_quote + 1e-12 < required_with_buffer:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="insufficient_quote_balance",
                symbol=resolved_symbol,
                required_quote=required_with_buffer,
                available_quote=float(available_quote),
                buffer_pct=buffer_pct,
            )
            return False

        self._last_buy_precheck_result = build_buy_precheck_result(
            ok=True,
            reason="ok",
            symbol=resolved_symbol,
            required_quote=required_with_buffer,
            available_quote=float(available_quote),
            buffer_pct=buffer_pct,
        )
        return True

    def get_last_buy_precheck_result(self) -> dict[str, Any] | None:
        """Return metadata from the most recent buy funds pre-check."""
        return self._last_buy_precheck_result

    async def get_free_balance_for_asset(
        self, config: dict[str, Any], asset: str
    ) -> float | None:
        """Return currently available balance for an asset symbol (e.g. USDC)."""
        await self.__ensure_exchange(config)
        return await self._balance_manager.get_free_balance_for_asset(asset)

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
        if not order:
            return None
        return await self._buy_manager.finalize_market_buy(
            order=order,
            config=self.config,
            parse_order_status=self.__parse_order_status,
            get_precision_for_symbol=self.__get_precision_for_symbol,
            resolve_symbol=self.__resolve_symbol,
            get_demo_taker_fee_for_symbol=self.__get_demo_taker_fee_for_symbol,
        )

    async def __execute_market_buy(
        self, order: dict[str, Any]
    ) -> dict[str, Any] | None:
        return await self._buy_manager.execute_market_buy(order)

    async def create_spot_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        return await self._sell_manager.create_spot_sell(
            order=order,
            config=config,
            create_spot_limit_sell=self.create_spot_limit_sell,
            create_spot_market_sell=self.create_spot_market_sell,
            can_fallback_to_market_sell=self.__can_fallback_to_market_sell,
        )

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

        return finalize_sell_order_status(
            order_status,
            total_cost=float(order["total_cost"]),
            actual_pnl=order["actual_pnl"],
        )

    async def create_spot_limit_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Create a spot limit sell order and delegate fill handling."""
        self.config = config
        return await self._limit_order_manager.create_spot_limit_sell(
            order=order,
            config=config,
            ensure_exchange=self.__ensure_exchange,
            ensure_markets_loaded=self.__ensure_markets_loaded,
            resolve_symbol=self.__resolve_symbol,
            resolve_sell_amount=self.__resolve_sell_amount,
            is_notional_below_minimum=self.__is_limit_sell_notional_below_minimum,
            get_price_for_symbol=self.__get_price_for_symbol,
            handle_limit_sell_fill=self.__handle_limit_sell_fill,
        )

    async def __handle_limit_sell_fill(
        self,
        sell_order: dict[str, Any],
        resolved_symbol: str,
        config: dict[str, Any],
        original_order: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Delegate limit-sell timeout and partial-fill reconciliation."""
        return await self._limit_sell_manager.handle_limit_sell_fill(
            sell_order=sell_order,
            resolved_symbol=resolved_symbol,
            config=config,
            original_order=original_order,
            parse_order_status=self.__parse_order_status,
            build_sell_order_status=self.__build_sell_order_status,
        )

    @retry(wait=wait_fixed(1), stop=stop_after_attempt(200))
    async def create_spot_market_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Create a spot market sell order via the sell manager."""
        self.config = config
        return await self._sell_manager.create_spot_market_sell(
            order=order,
            config=config,
            ensure_exchange=self.__ensure_exchange,
            ensure_markets_loaded=self.__ensure_markets_loaded,
            resolve_symbol=self.__resolve_symbol,
            resolve_sell_amount=self.__resolve_sell_amount,
            reduce_amount_by_step=self.__reduce_amount_by_step,
            is_notional_below_minimum=self.__is_market_sell_notional_below_minimum,
            get_price_for_symbol=self.__get_price_for_symbol,
            log_remaining_sell_dust=self.__log_remaining_sell_dust,
            build_sell_order_status=self.__build_sell_order_status,
        )
