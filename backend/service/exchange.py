"""Exchange service for CCXT async operations."""

import asyncio
import decimal
from typing import Any

import ccxt.async_support as ccxt
import helper
from tenacity import TryAgain, retry, stop_after_attempt, wait_fixed

logging = helper.LoggerFactory.get_logger("logs/exchange.log", "exchange")


class Exchange:
    """Exchange wrapper for CCXT async operations."""

    HISTORY_RETRY_SLEEP_SECONDS = 1
    HISTORY_MAX_CONSECUTIVE_ERRORS = 5

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

    async def __close_exchange(self) -> None:
        if self.exchange is None:
            return

        try:
            await self.exchange.close()
        except Exception as exc:
            logging.warning(f"Failed to close exchange client cleanly: {exc}")
        finally:
            self.exchange = None
            self._markets_loaded = False
            self._exchange_config = None

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
        except Exception:
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
                    resolved = market.get("symbol") if isinstance(market, dict) else None
                    if isinstance(resolved, str):
                        return resolved
                except Exception:
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
            logging.error(f"Error converting timestamp due to an exchange error: {e}")
            raise TryAgain
        except ccxt.NetworkError as e:
            logging.error(f"Error converting timestamp due to a network error: {e}")
            raise TryAgain
        except ccxt.BaseError as e:
            logging.error(f"Converting timestamp failed due to an error: {e}")
            raise TryAgain
        except Exception as e:
            # Broad catch to retry on unexpected exchange errors.
            logging.error(f"Converting timestamp failed with: {e}")
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
            logging.error(f"{symbol} not found")
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

            except (
                Exception,
                ccxt.NetworkError,
                ccxt.ExchangeError,
                ccxt.BaseError,
            ) as e:
                # Broad catch to continue paging through historical data.
                logging.error(f"Fetching historical data failed due to an error: {e}")
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
                raise TryAgain
            # Fetch the ticker data for the trading pair
            ticker = await self.exchange.fetch_ticker(resolved_pair)
            # Extract the actual price from the ticker data
            if not ticker["last"]:
                raise TryAgain
            actual_price = float(ticker["last"])
            result = self.exchange.price_to_precision(resolved_pair, actual_price)
        except ccxt.ExchangeError as e:
            logging.error(
                f"Fetching ticker messages failed due to an exchange error: {e}"
            )
            raise TryAgain
        except ccxt.NetworkError as e:
            logging.error(
                f"Fetching ticker messages failed due to a network error: {e}"
            )
            raise TryAgain
        except ccxt.BaseError as e:
            logging.error(f"Fetching ticker messages failed due to an error: {e}")
            raise TryAgain
        except Exception as e:
            # Broad catch to retry on unexpected exchange errors.
            logging.error(f"Fetching ticker messages failed with: {e}")
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
            logging.error(f"Fetching market data failed due to an exchange error: {e}")
            raise TryAgain
        except ccxt.NetworkError as e:
            logging.error(f"Fetching market data failed due to a network error: {e}")
            raise TryAgain
        except ccxt.BaseError as e:
            logging.error(f"Fetching market data failed due to an error: {e}")
            raise TryAgain
        except Exception as e:
            # Broad catch to retry on unexpected exchange errors.
            logging.error(f"FFetching market data failed failed with: {e}")
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

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    async def __get_trades_for_symbol(self, symbol: str, orderid: str) -> dict | None:
        trade = None
        await asyncio.sleep(1)
        since = self.exchange.milliseconds() - (
            self.config.get("order_check_range", 5) * 1000
        )  # X seconds from now
        try:
            trade = {}
            amount = 0.0
            fee = 0.0
            cost = 0.0
            orderlist = await self.exchange.fetch_my_trades(symbol, since)
            if orderlist:
                logging.debug(
                    f"Orderlist for {symbol} with orderid: {orderid}: {orderlist}"
                )

                for order in orderlist:
                    # Avoid merging different orders in high volatility scenarios
                    if order["order"] == orderid:
                        amount += order["amount"]
                        fee += order["fee"]["cost"]
                        cost += order["cost"]

                trade["cost"] = cost
                trade["fee"] = fee
                trade["amount"] = amount
                trade["timestamp"] = orderlist[-1]["timestamp"]
                trade["price"] = orderlist[-1]["price"]
                trade["order"] = orderlist[-1]["order"]
                trade["symbol"] = orderlist[-1]["symbol"]
                trade["side"] = orderlist[-1]["side"]
                trade["fee_cost"] = orderlist[-1]["fee"]
        except ccxt.NetworkError as e:
            logging.error(f"Fetch trade order failed due to a network error: {e}")
            raise TryAgain
        except ccxt.ExchangeError as e:
            logging.error(f"Fetch trade order failed due to an exchange error: {e}")
            raise TryAgain
        except ccxt.BaseError as e:
            logging.error(f"Fetch trade order failed due to an error: {e}")
            raise TryAgain
        except Exception as e:
            # Broad catch to retry on unexpected exchange errors.
            logging.error(f"Fetch trade order failed with: {e}")
            raise TryAgain

        return trade

    async def __parse_order_status(self, order: dict[str, Any]) -> dict[str, Any]:
        data = {}

        trade = await self.__get_trades_for_symbol(order["symbol"], order["id"])
        if trade:
            data["timestamp"] = trade["timestamp"]
            data["amount"] = float(trade["amount"])
            data["total_amount"] = float(trade["amount"])
            data["price"] = trade["price"]
            data["orderid"] = trade["order"]
            data["symbol"] = trade["symbol"]
            data["side"] = trade["side"]
            data["amount_fee"] = trade["fee_cost"]
            data["ordersize"] = order["cost"]
        else:
            logging.info(
                f"Getting trades for {order['symbol']} failed - using information of order."
            )
            data["timestamp"] = order["timestamp"]
            data["amount"] = float(order["amount"])
            data["total_amount"] = float(order["amount"])
            data["price"] = order["price"]
            data["orderid"] = order["id"]
            data["symbol"] = order["symbol"]
            data["side"] = order["side"]
            data["amount_fee"] = order["fee"]
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
                f"Getting amount for {symbol} failed due to a network error: {e}"
            )
            raise TryAgain
        except ccxt.ExchangeError as e:
            logging.error(
                f"Getting amount for {symbol} failed due to an exchange error: {e}"
            )
            raise TryAgain
        except ccxt.BaseError as e:
            logging.error(f"Getting amount for {symbol} failed due to an error: {e}")
            raise TryAgain
        except Exception as e:
            # Broad catch to retry on unexpected exchange errors.
            logging.error(f"Getting amount for {symbol} failed with: {e}")
            raise TryAgain

        return amount

    async def __init_exchange(self, config: dict[str, Any]):
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
                except Exception as exc:
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
        try:
            logging.info(f"Try to buy {order['amount']} {order['symbol']}")
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
        except ccxt.ExchangeError as e:
            logging.error(
                f"Buying pair {order['symbol']} failed due to an exchange error: {e}"
            )
            order = None
        except ccxt.NetworkError as e:
            logging.error(
                f"Buying pair {order['symbol']} failed due to an network error: {e}"
            )
            order = None
        except ccxt.BaseError as e:
            logging.error(f"Buying pair {order['symbol']} failed due to an error: {e}")
            order = None
        except Exception as e:
            # Broad catch to surface unexpected exchange errors.
            logging.error(f"Buying pair {order['symbol']} failed with: {e}")
            order = None

        if order:
            logging.info(f"Opened trade: {order}")

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
            order["amount"] = float(order_status["amount"])
            order["amount_fee"] = 0.0
            order["fees"] = 0.0

            # Substract the order fees
            if not self.config.get("fee_deduction", False):
                if self.config.get("dry_run", True):
                    try:
                        order["fees"] = self.__get_demo_taker_fee_for_symbol(
                            order_status["symbol"]
                        )
                    except Exception as e:
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
                        order["fees"] = fees["taker"]
                    except ccxt.ExchangeError as e:
                        logging.error(
                            f"Fetching fee for pair {order['symbol']} failed due to an exchange error: {e}"
                        )
                        order = None
                    except ccxt.NetworkError as e:
                        logging.error(
                            f"Fetching fee for pair {order['symbol']} failed due to an network error: {e}"
                        )
                        order = None
                    except ccxt.BaseError as e:
                        logging.error(
                            f"Fetching fee for pair {order['symbol']} failed due to an error: {e}"
                        )
                        order = None
                    except Exception as e:
                        # Broad catch to surface unexpected exchange errors.
                        logging.error(
                            f"Fetching fee for pair {order['symbol']} failed with: {e}"
                        )
                        order = None
                    if order is None:
                        return None
                order["amount_fee"] = order["amount"] * float(order["fees"])
                order["amount"] = float(order_status["amount"]) - order["amount_fee"]

                logging.debug(
                    "Fee Deduction not active. Real amount "
                    f"{order_status['amount']}, deducted amount {order['amount']}"
                )

            logging.debug(order)

            return order

    async def create_spot_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Create a sell order using configured execution mode."""
        sell_order_type = str(config.get("sell_order_type", "market")).lower()
        if sell_order_type == "limit":
            order_status = await self.create_spot_limit_sell(order, config)
            if order_status:
                return order_status

            if bool(config.get("limit_sell_fallback_to_market", True)):
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

    async def __build_sell_order_status(
        self, order: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Build normalized sell order status for closed trade processing."""
        order_status = await self.__parse_order_status(order)
        if not order_status.get("total_amount"):
            logging.error("Sell order for %s returned empty amount.", order.get("symbol"))
            return None

        order_status["type"] = "sold_check"
        order_status["sell"] = True
        order_status["total_cost"] = order["total_cost"]
        order_status["actual_pnl"] = order["actual_pnl"]
        order_status["avg_price"] = order_status["total_cost"] / order_status["total_amount"]
        order_status["tp_price"] = order_status["price"]
        order_status["profit"] = (
            order_status["price"] * order_status["total_amount"] - order_status["total_cost"]
        )
        order_status["profit_percent"] = (
            (order_status["price"] - order_status["avg_price"]) / order_status["avg_price"]
        ) * 100
        return order_status

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
            except Exception as exc:
                logging.warning("Polling limit sell status failed: %s", exc)

            await asyncio.sleep(1)

        return None

    async def __cancel_order_safe(self, symbol: str, order_id: str) -> None:
        """Cancel an order and only log failures."""
        try:
            await self.exchange.cancel_order(order_id, symbol)
        except Exception as exc:
            logging.warning(
                "Cancel order %s for %s failed or order is already closed: %s",
                order_id,
                symbol,
                exc,
            )

    async def create_spot_limit_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Create a spot limit sell order and wait for fill."""
        await self.__ensure_exchange(config)
        await self.__ensure_markets_loaded()
        self.config = config

        resolved_symbol = self.__resolve_symbol(order["symbol"])
        if resolved_symbol is None:
            logging.error("Cannot place limit sell. Symbol not found: %s", order["symbol"])
            return None

        try:
            amount = self.exchange.amount_to_precision(
                resolved_symbol, float(order["total_amount"])
            )
            if not amount or float(amount) <= 0:
                logging.error(
                    "Skipping limit sell for %s: invalid amount %s",
                    resolved_symbol,
                    amount,
                )
                return None

            current_price = order.get("current_price")
            if current_price and float(current_price) > 0:
                limit_price = self.exchange.price_to_precision(
                    resolved_symbol, float(current_price)
                )
            else:
                live_price = await self.__get_price_for_symbol(resolved_symbol)
                limit_price = self.exchange.price_to_precision(
                    resolved_symbol, float(live_price)
                )

            logging.info(
                "Placing limit sell for %s amount=%s price=%s",
                resolved_symbol,
                amount,
                limit_price,
            )
            parameter = {}
            trade = await self.exchange.create_order(
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
            logging.error("Limit sell for %s failed due to an error: %s", order["symbol"], exc)
            return None
        except Exception as exc:
            logging.error("Limit sell for %s failed with: %s", order["symbol"], exc)
            return None

        sell_order = dict(order)
        sell_order.update(trade)
        sell_order["symbol"] = resolved_symbol
        sell_order["total_amount"] = float(amount)
        if not sell_order.get("id"):
            logging.error("Limit sell for %s returned no order id.", resolved_symbol)
            return None

        try:
            timeout_seconds = max(1, int(config.get("limit_sell_timeout_sec", 60)))
        except (TypeError, ValueError):
            timeout_seconds = 60
        filled_order = await self.__wait_for_limit_sell_fill(
            resolved_symbol, str(sell_order["id"]), timeout_seconds
        )
        if not filled_order:
            logging.info(
                "Limit sell for %s was not filled within %s seconds.",
                resolved_symbol,
                timeout_seconds,
            )
            await self.__cancel_order_safe(resolved_symbol, str(sell_order["id"]))
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
        self.config = config
        try:
            # Implement sell safeguard, if we cannot sell full amount
            if Exchange.sell_retry_count > 0:
                int_amount = len(str(int(order["total_amount"])))
                decimal_places = abs(
                    decimal.Decimal(str(order["total_amount"])).as_tuple().exponent
                )
                if int_amount >= 3:
                    reduce_amount = Exchange.sell_retry_count
                else:
                    reduce_amount = Exchange.sell_retry_count * (10**-decimal_places)
                order["total_amount"] = order["total_amount"] - reduce_amount
                logging.info(f"Reducing amount for sell to: {order['total_amount']}")

            trade = await self.exchange.create_market_sell_order(
                order["symbol"], order["total_amount"]
            )
            # TODO: Check if there is dust left to sell
            # 1. fetch the amount left
            # 2. createConvertTrade (ccxt)
            # 3. fetchConvertTrade (ccxt)
            order.update(trade)
        except ccxt.ExchangeError as e:
            if "insufficient balance" in str(e):
                logging.error(
                    f"Trying to sell {order['total_amount']} of pair {order['symbol']} failed due insufficient balance."
                )
                Exchange.sell_retry_count += 1
                raise TryAgain
            else:
                logging.error(
                    f"Selling pair {order['symbol']} failed due to an exchange error: {e}"
                )
                order = None
        except ccxt.NetworkError as e:
            logging.error(
                f"Selling pair {order['symbol']} failed due to an network error: {e}"
            )
            order = None
        except ccxt.BaseError as e:
            logging.error(f"Selling pair {order['symbol']} failed due to an error: {e}")
            order = None
        except Exception as e:
            # Broad catch to surface unexpected exchange errors.
            logging.error(f"Selling pair {order['symbol']} failed with: {e}")
            order = None

        if order:
            logging.info(f"Sold {order['total_amount']} {order['symbol']} on Exchange.")
            Exchange.sell_retry_count = 0
            return await self.__build_sell_order_status(order)
