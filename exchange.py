import asyncio
import ccxt as ccxt
import uuid
import time
from models import Trades
from tortoise.functions import Sum

from logger import LoggerFactory


class Exchange:
    def __init__(
        self,
        order,
        tickers,
        exchange,
        key,
        secret,
        currency,
        sandbox,
        market,
        leverage,
        dry_run,
        loglevel,
    ):
        self.currency = currency.upper()
        self.leverage = leverage
        self.market = market
        self.dry_run = dry_run

        # Exchange configuration
        self.exchange_id = exchange
        self.exchange_class = getattr(ccxt, self.exchange_id)
        self.exchange = self.exchange_class(
            {
                "apiKey": key,
                "secret": secret,
            }
        )
        self.exchange.set_sandbox_mode(sandbox)
        self.exchange.options["defaultType"] = market
        self.exchange.enableRateLimit = True
        self.exchange.load_markets()

        # Class Attributes
        Exchange.order = order
        Exchange.tickers = tickers
        Exchange.logging = LoggerFactory.get_logger(
            "exchange.log", "exchange", log_level=loglevel
        )
        Exchange.logging.info("Initialized")

    def __price(self, pair):
        try:
            # Fetch the ticker data for the trading pair
            ticker = self.exchange.fetch_ticker(pair)
            # Extract the actual price from the ticker data
            actual_price = ticker["last"]
            result = actual_price
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

    def __parse_order_status(self, order):
        if order["price"] == None:
            # Bybit does not send useful information as order response
            # so we fetch it from the exchange
            order = self.exchange.fetch_order(order["id"], order["symbol"])
            order["amount"] = order["filled"]
            Exchange.logging.debug(f"order status: {order}")

        data = {}
        if order["timestamp"]:
            data["timestamp"] = order["timestamp"]
        else:
            data["timestamp"] = order["info"]["updateTime"]
        data["amount"] = order["amount"]
        data["price"] = order["price"]
        data["orderid"] = order["info"]["orderId"]
        data["symbol"] = order["symbol"]
        data["side"] = order["side"]
        data["type"] = order["type"]

        return data

    def __get_amount_from_symbol(self, ordersize, symbol):
        price = self.__price(symbol)

        return ordersize / price

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

    def __buy(self, ordersize, pair, position):
        # Variables
        results = None
        order = {}
        parameter = {}
        amount = self.__get_amount_from_symbol(ordersize, pair)
        price = self.__price(pair)

        if position == "short":
            side = "sell"
        else:
            side = "buy"

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
            order["timestamp"] = "dryrun"
            order["amount"] = amount
            order["price"] = price
            order["symbol"] = pair
            order["type"] = "market"
            order["side"] = side
            time.sleep(0.2)
            results = order
        else:
            try:
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
        price = self.__price(pair)

        if position == "short":
            side = "buy"
        else:
            side = "sell"

        # Future options
        if self.market == "future" and self.exchange_id == "binance":
            parameter = {"positionSide": position}

        if self.dry_run:
            order["symbol"] = True
            time.sleep(0.2)
            results = order
        else:
            try:
                order = self.exchange.create_order(
                    pair, "market", side, amount, price, parameter
                )

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
            # Add database entries after exchange trade
            order_status = self.__parse_order_status(trade)
            await Trades.create(
                timestamp=order_status["timestamp"],
                ordersize=order["ordersize"],
                amount=order_status["amount"],
                price=order_status["price"],
                symbol=order_status["symbol"],
                orderid=order_status["orderid"],
                bot=order["botname"],
                ordertype=order["ordertype"],
                baseorder=order["baseorder"],
                safetyorder=order["safetyorder"],
                order_count=order["order_count"],
                so_percentage=order["so_percentage"],
                direction=order["direction"],
                side=order_status["side"],
            )

            Exchange.logging.info(f"Opened order: {order}")

            # Update tickers for tickers watcher
            tickers = await self.__get_symbols()
            await Exchange.tickers.put(tickers)

    async def __sell_order(self, order):
        close = None

        # Get token amount from trades
        amount = (
            await Trades.filter(bot=order["botname"])
            .annotate(total_amount=Sum("amount"))
            .values("total_amount")
        )
        amount = amount[0]["total_amount"]

        trade = self.__sell(amount, order["symbol"], order["direction"])

        # Delete database entries after exchange trade
        if trade:
            # Delete database entries
            await Trades.filter(bot=order["botname"]).delete()

            Exchange.logging.info(f"Sold order: {order}")

            # Update tickers for tickers watcher
            tickers = await self.__get_symbols()
            # Not sending empty symbol list (watcher_tickes needs at least one!)
            if tickers:
                await Exchange.tickers.put(tickers)

    async def __process_order(self, order):
        Exchange.logging.debug(f"New order: {order}")

        order["symbol"] = self.__split_symbol(order["symbol"])
        order["direction"] = self.__split_direction(order["direction"])

        if order["side"] == "buy":
            await self.__buy_order(order)
        if order["side"] == "sell":
            await self.__sell_order(order)

    async def run(self):
        while True:
            order = await Exchange.order.get()
            await self.__process_order(order)
