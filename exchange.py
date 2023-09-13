import asyncio
import ccxt as ccxt
from models import Trades
from tortoise.functions import Sum

from logger import Logger


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
    ):
        self.order = order
        self.tickers = tickers
        self.currency = currency.upper()
        self.leverage = leverage
        self.market = market

        # Exchange configuration
        self.exchange_id = exchange
        self.exchange_class = getattr(ccxt, self.exchange_id)
        self.exchange = self.exchange_class(
            {
                "apiKey": key,
                "secret": secret,
                "options": {
                    "defaultType": market,
                },
            },
        )
        self.exchange.set_sandbox_mode(sandbox)
        self.exchange.enableRateLimit = True
        self.exchange.loadMarkets()

        # Logging
        self.logging = Logger("main")
        self.logging.info("Exchange module: Initialize exchange connection")

    def __price(self, pair):
        try:
            # Fetch the ticker data for the trading pair
            ticker = self.exchange.fetch_ticker(pair)
            # Extract the actual price from the ticker data
            actual_price = ticker["last"]
            result = actual_price
        except ccxt.ExchangeError as e:
            self.logging.error(
                f"Fetching ticker messages failed due to an exchange error: {e}"
            )
            result = None
        except ccxt.NetworkError as e:
            self.logging.error(
                f"Fetching ticker messages failed due to a network error: {e}"
            )
            result = None

        return result

    def __parse_order_status(self, order):
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

    def __buy(self, ordersize, pair, positionSide):
        results = None
        position = {}
        # Set leverage for futures
        # if self.market == "future":
        #     symbol = self.exchange.market(pair)
        #     leverage = self.exchange.fapiPrivate_post_leverage(
        #         {
        #             "symbol": symbol["id"],
        #             "leverage": self.leverage,
        #         }
        #     )

        amount = self.__get_amount_from_symbol(ordersize, pair)
        if self.market == "future":
            position = {"positionSide": positionSide}
            if self.leverage > 1:
                # Adapt amount to reflect leverage
                amount = amount * self.leverage

        order = None
        self.logging.info("Buy pair " + str(pair))
        try:
            if positionSide == "short":
                order = self.exchange.createMarketSellOrder(pair, amount, position)
            else:
                order = self.exchange.createMarketBuyOrder(pair, amount, position)

            if order:
                results = order
            else:
                results = None
        except ccxt.ExchangeError as e:
            self.logging.error(
                f"Buying pair {pair} failed due to an exchange error: {e}"
            )
            results = None
        except ccxt.NetworkError as e:
            self.logging.error(
                f"Buying pair {pair} failed due to an network error: {e}"
            )
            results = None

        return results

    def __sell(self, amount, pair, positionSide):
        results = None
        order = None
        position = {}

        if self.market == "future":
            position = {"positionSide": positionSide}

        self.logging.info("Sell pair " + str(pair))

        try:
            if positionSide == "short":
                order = self.exchange.createMarketBuyOrder(pair, amount, position)
            else:
                order = self.exchange.createMarketSellOrder(pair, amount, position)

            if order:
                results = order
            else:
                results = None
        except ccxt.ExchangeError as e:
            self.logging.error(
                f"Selling pair {pair} failed due to an exchange error: {e}"
            )
            results = None
        except ccxt.NetworkError as e:
            self.logging.error(
                f"Selling pair {pair} failed due to an network error: {e}"
            )
            results = None

        return results

    def __split_symbol(self, pair):
        symbol = pair
        if not "/" in pair:
            pair = pair.split(self.currency)
            symbol = pair[0] + "/" + self.currency
        return symbol

    def __split_direction(self, direction):
        if "_" in direction:
            direction = direction.split("_")
        return direction[1]

    async def __buy_order(self, order):
        self.logging.info(f"Open {order['direction']} trade for pair {order['symbol']}")

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

            # Update tickers for tickers watcher
            tickers = await self.__get_symbols()
            await self.tickers.put(tickers)

    async def __sell_order(self, order):
        close = None
        self.logging.info(f"Sell {order['direction']} order for pair {order['symbol']}")

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

            # Update tickers for tickers watcher
            tickers = await self.__get_symbols()
            # Not sending empty symbol list (watcher_tickes needs at least one!)
            if tickers:
                await self.tickers.put(tickers)

    async def __process_order(self, order):
        self.logging.debug(f"Exchange module: Got a new order! {order}")

        order["symbol"] = self.__split_symbol(order["symbol"])
        order["direction"] = self.__split_direction(order["direction"])

        if order["side"] == "buy":
            await self.__buy_order(order)
        if order["side"] == "sell":
            await self.__sell_order(order)

    async def run(self):
        while True:
            order = await self.order.get()
            await self.__process_order(order)
