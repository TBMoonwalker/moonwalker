import asyncio
import ccxt as ccxt
import uuid
import time
from datetime import datetime
from models import Trades
from tortoise.functions import Sum
from tenacity import retry, stop_after_attempt

from logger import LoggerFactory


class Exchange:
    def __init__(
        self,
        order,
        tickers,
        exchange,
        key,
        secret,
        password,
        currency,
        sandbox,
        market,
        leverage,
        margin_type,
        dry_run,
        loglevel,
        fee_deduction,
        statistic,
    ):
        self.currency = currency.upper()
        self.leverage = leverage
        self.margin_type = margin_type.upper()
        self.market = market
        self.dry_run = dry_run
        self.fee_deduction = fee_deduction

        # Exchange configuration
        login_params = {
            "apiKey": key,
            "secret": secret,
        }
        self.exchange_id = exchange
        self.exchange_class = getattr(ccxt, self.exchange_id)
        if self.exchange_id == "okx":
            login_params.update({"password": password})

        self.exchange = self.exchange_class(login_params)
        self.exchange.set_sandbox_mode(sandbox)
        self.exchange.options["defaultType"] = self.market
        self.exchange.enableRateLimit = True
        self.exchange.load_markets()

        # Class Attributes
        Exchange.order = order
        Exchange.tickers = tickers
        Exchange.statistic = statistic
        Exchange.logging = LoggerFactory.get_logger(
            "exchange.log", "exchange", log_level=loglevel
        )
        Exchange.logging.info("Initialized")

    def __get_price_for_symbol(self, pair):
        try:
            # Fetch the ticker data for the trading pair
            ticker = self.exchange.fetch_ticker(pair)
            # Extract the actual price from the ticker data
            actual_price = float(ticker["last"])
            result = self.exchange.price_to_precision(pair, actual_price)
        except ccxt.ExchangeError as e:
            Exchange.logging.error(
                f"Fetching ticker messages failed due to an exchange error: {e}"
            )
            result = None
        except ccxt.NetworkError as e:
            Exchange.logging.error(
                f"Fetching ticker messages failed due to a network error: {e}"
            )
            result = None

        return result

    def __get_precision_for_symbol(self, pair):
        market = self.exchange.market(pair)
        return market["precision"]["amount"]

    def __parse_order_status(self, order):
        # if order["price"] == None:
        #     # Bybit does not send useful information as order response
        #     # so we fetch it from the exchange
        #     order = self.exchange.fetch_order(order["id"], order["symbol"])
        #     order["amount"] = order["filled"]
        #     order["price"] = order["average"]
        #     Exchange.logging.debug(f"order status: {order}")
        data = {}

        if self.dry_run:
            data["timestamp"] = order["timestamp"]
            data["amount"] = order["amount"]
            data["price"] = order["price"]
            data["orderid"] = order["info"]["orderId"]
            data["symbol"] = order["symbol"]
            data["side"] = order["side"]
            data["type"] = order["type"]
        else:
            since = self.exchange.milliseconds() - 5000  # -5 seconds from now
            order = self.exchange.fetch_my_trades(order["symbol"], since)
            data["timestamp"] = order[-1]["timestamp"]
            data["amount"] = float(order[-1]["amount"]) - float(
                order[-1]["fee"]["cost"]
            )
            data["price"] = order[-1]["price"]
            data["orderid"] = order[-1]["order"]
            data["symbol"] = order[-1]["symbol"]
            data["side"] = order[-1]["side"]
            data["amount_fee"] = order[-1]["fee"]["cost"]
            data["ordersize"] = order[-1]["cost"]

        return data

    def __get_amount_from_symbol(self, ordersize, symbol) -> float:
        price = self.__get_price_for_symbol(symbol)
        amount = self.exchange.amount_to_precision(
            symbol, float(ordersize) / float(price)
        )

        return amount

    async def __get_symbols(self):
        data = await Trades.all().distinct().values_list("symbol", flat=True)
        return data

    def __split_symbol(self, pair):
        symbol = pair
        if not "/" in pair:
            pair, currency = pair.split(self.currency)
            if self.market == "future":
                symbol = f"{pair}/{self.currency}:{self.currency}"
            else:
                symbol = f"{pair}/{self.currency}"
        return symbol

    def __split_direction(self, direction):
        if "_" in direction:
            type, direction = direction.split("_")
        return direction

    @retry(stop=stop_after_attempt(3))
    async def __add_trade(self, order):
        # Add database entries on successful trade order
        try:
            await Trades.create(
                timestamp=order["timestamp"],
                ordersize=order["ordersize"],
                fee=order["fees"],
                precision=order["precision"],
                amount_fee=order["amount_fee"],
                amount=order["amount"],
                price=order["price"],
                symbol=order["symbol"],
                orderid=order["orderid"],
                bot=order["botname"],
                ordertype=order["ordertype"],
                baseorder=order["baseorder"],
                safetyorder=order["safetyorder"],
                order_count=order["order_count"],
                so_percentage=order["so_percentage"],
                direction=order["direction"],
                side=order["side"],
            )
            result = True
        except Exception as e:
            self.logging.error(f"Error adding trade to database: {e}")
            result = False

        return result

    @retry(stop=stop_after_attempt(3))
    async def __delete_trade(self, order):
        # Delete database entries after trade sell
        try:
            await Trades.filter(bot=order["botname"]).delete()
            result = True
        except Exception as e:
            self.logging.error(f"Error deleting trade from database: {e}")
            result = False

        return result

    def __buy(self, ordersize, pair, position):
        # Variables
        results = None
        order = {}
        parameter = {}
        amount = self.__get_amount_from_symbol(ordersize, pair)
        price = self.__get_price_for_symbol(pair)

        if position == "short":
            side = "sell"
            dryrun_side = "buy"
        else:
            side = "buy"
            dryrun_side = "sell"

        # Future options
        if self.market == "future":
            symbol = self.exchange.market(pair)
            if self.exchange_id == "binance":
                parameter = {"positionSide": position}
                try:
                    self.exchange.fapiprivate_post_leverage(
                        {
                            "symbol": symbol["id"],
                            "leverage": self.leverage,
                        }
                    )
                    self.exchange.fapiprivate_post_margintype(
                        {
                            "symbol": symbol["id"],
                            "marginType": self.margin_type,
                        }
                    )
                except ccxt.ExchangeError as e:
                    self.logging.error(e)
            else:
                try:
                    self.exchange.set_leverage(self.leverage, pair)
                except ccxt.ExchangeError as e:
                    self.logging.error(e)

        if self.dry_run:
            order["info"] = {}
            order["info"]["orderId"] = uuid.uuid4()
            order["timestamp"] = time.mktime(datetime.now().timetuple()) * 1000
            order["amount"] = amount
            order["price"] = price
            order["symbol"] = pair
            order["type"] = "market"
            order["side"] = dryrun_side
            time.sleep(0.2)
            results = order
        else:
            try:
                self.logging.debug(f"Try to buy {amount} {pair}")
                order = self.exchange.create_order(
                    pair, "market", side, amount, price, parameter
                )

                if order:
                    results = order
                else:
                    results = None
            except ccxt.ExchangeError as e:
                Exchange.logging.error(
                    f"Buying pair {pair} failed due to an exchange error: {e}"
                )
                results = None
            except ccxt.NetworkError as e:
                Exchange.logging.error(
                    f"Buying pair {pair} failed due to an network error: {e}"
                )
                results = None

        return results

    def __sell(self, amount, pair, position):
        results = None
        order = {}
        parameter = {}
        price = self.__get_price_for_symbol(pair)

        if self.dry_run:
            order["symbol"] = True
            time.sleep(0.2)
            results = order
        else:
            try:
                # Future order
                if self.market == "future":
                    if position == "short":
                        side = "buy"
                    else:
                        side = "sell"

                    if self.exchange_id == "binance":
                        parameter = {"positionSide": position}

                    order = self.exchange.create_order(
                        pair, "market", side, amount, price, parameter
                    )
                # Spot order
                else:
                    order = self.exchange.create_market_sell_order(pair, amount)

                if order:
                    results = order
                else:
                    results = None
            except ccxt.ExchangeError as e:
                Exchange.logging.error(
                    f"Selling pair {pair} failed due to an exchange error: {e}"
                )
                results = None
            except ccxt.NetworkError as e:
                Exchange.logging.error(
                    f"Selling pair {pair} failed due to an network error: {e}"
                )
                results = None

        return results

    async def __buy_order(self, order):
        trade = self.__buy(order["ordersize"], order["symbol"], order["direction"])

        if trade:
            Exchange.logging.info(f"Opened order: {order}")

            order_status = self.__parse_order_status(trade)
            order.update(order_status)
            order["precision"] = self.__get_precision_for_symbol(order_status["symbol"])
            order["amount"] = float(order_status["amount"])
            order["amount_fee"] = 0

            # Substract the order fees (on Future - Fees will be deducted in Quote not Base)
            if not self.fee_deduction or self.market == "future":
                order["fees"] = self.exchange.fetch_trading_fee(
                    symbol=order_status["symbol"]
                )["taker"]
                order["amount_fee"] = order["amount"] * float(order["fees"])
                order["amount"] = float(order_status["amount"]) - order["amount_fee"]

            # Add trade to database and push message to Watcher
            if await self.__add_trade(order):
                # Update tickers for tickers watcher
                tickers = await self.__get_symbols()
                await Exchange.tickers.put(tickers)
            else:
                self.logging.error(
                    "Error adding trade to database - trade will not automatically traded by Moonwalker!"
                )

    async def __sell_order(self, order):
        close = None

        # Get token amount from trades
        amount = (
            await Trades.filter(bot=order["botname"])
            .annotate(total_amount=Sum("amount"))
            .values("total_amount")
        )
        amount = amount[0]["total_amount"]
        self.logging.debug(f"Selling {amount} {order['symbol']}")

        trade = self.__sell(amount, order["symbol"], order["direction"])

        if trade:
            Exchange.logging.info(f"Sold order: {order}")

            # Delete trade from database and push message to Statistics
            if await self.__delete_trade(order):
                # Update statistics
                if not self.dry_run:
                    order_status = self.__parse_order_status(trade)
                    data = {}
                    data["type"] = "sold_check"
                    data["sell"] = True
                    data["symbol"] = order_status["symbol"]
                    data["total_amount"] = order_status["amount"]
                    data["total_cost"] = order_status["ordersize"]
                    data["current_price"] = order_status["price"]
                    data["tp_price"] = order_status["price"]
                    data["avg_price"] = data["total_cost"] / data["total_amount"]
                    await Exchange.statistic.put(data)

                # Update tickers for tickers watcher
                tickers = await self.__get_symbols()
                # Not sending empty symbol list (watcher_tickes needs at least one!)
                if tickers:
                    await Exchange.tickers.put(tickers)
            else:
                self.logging.error(
                    "Error deleting trade from database - trade is done on Exchange, but not on Moonwalker Bot"
                )

    async def __process_order(self, data):
        Exchange.logging.debug(f"New order: {data}")

        data["symbol"] = self.__split_symbol(data["symbol"])
        data["direction"] = self.__split_direction(data["direction"])

        if data["side"] == "buy":
            await self.__buy_order(data)
        if data["side"] == "sell" and "type_sell" in data:
            self.logging.debug(f"Who likes to sell? {data}")
            await self.__sell_order(data)

    async def run(self):
        while True:
            data = await Exchange.order.get()
            await self.__process_order(data)
