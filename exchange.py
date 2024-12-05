import ccxt as ccxt
import uuid
import time
from datetime import datetime
from models import Trades
from tortoise.functions import Sum
from tenacity import retry, TryAgain, stop_after_attempt, wait_fixed

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
        dry_run,
        loglevel,
        fee_deduction,
        statistic,
    ):
        self.currency = currency.upper()
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
        Exchange.status = True
        Exchange.order = order
        Exchange.tickers = tickers
        Exchange.statistic = statistic
        Exchange.logging = LoggerFactory.get_logger(
            "logs/exchange.log", "exchange", log_level=loglevel
        )
        Exchange.logging.info("Initialized")

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    def __get_price_for_symbol(self, pair):
        """Gets the actual price for the given symbol/currency pair

        Parameters
        ----------
        pair: string
           Pair - has to be in format "symbol"/currency" (Example: BTC/USDT)

        Returns
        -------
        int
            Actual price with correct precision for that pair
        """
        result = None

        try:
            # Fetch the ticker data for the trading pair
            ticker = self.exchange.fetch_ticker(pair)
            # Extract the actual price from the ticker data
            if not ticker["last"]:
                raise TryAgain
            actual_price = float(ticker["last"])
            result = self.exchange.price_to_precision(pair, actual_price)
        except ccxt.ExchangeError as e:
            Exchange.logging.error(
                f"Fetching ticker messages failed due to an exchange error: {e}"
            )
            raise TryAgain
        except ccxt.NetworkError as e:
            Exchange.logging.error(
                f"Fetching ticker messages failed due to a network error: {e}"
            )
            raise TryAgain
        except Exception as e:
            Exchange.logging.error(f"Fetching ticker messages failed with: {e}")
            raise TryAgain

        return result

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    def __get_precision_for_symbol(self, pair):

        result = None

        try:
            market = self.exchange.market(pair)
            result = market["precision"]["amount"]
        except ccxt.ExchangeError as e:
            Exchange.logging.error(
                f"Fetching market data failed due to an exchange error: {e}"
            )
            raise TryAgain
        except ccxt.NetworkError as e:
            Exchange.logging.error(
                f"Fetching market data failed due to a network error: {e}"
            )
            raise TryAgain
        except Exception as e:
            Exchange.logging.error(f"FFetching market data failed failed with: {e}")
            raise TryAgain

        return result

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    def __get_trades_for_symbol(self, symbol):
        trade = None
        time.sleep(1)
        since = self.exchange.milliseconds() - 5000  # -5 seconds from now
        try:
            trade = {}
            amount = 0.0
            fee = 0.0
            cost = 0.0
            orderlist = self.exchange.fetch_my_trades(symbol, since)
            if orderlist:
                Exchange.logging.debug(f"Orderlist for {symbol}: {orderlist}")

                for order in orderlist:
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
            Exchange.logging.error(
                f"Fetch trade order failed due to a network error: {e}"
            )
            raise TryAgain
        except ccxt.ExchangeError as e:
            Exchange.logging.error(
                f"Fetch trade order failed due to an exchange error: {e}"
            )
            raise TryAgain
        except Exception as e:
            Exchange.logging.error(f"Fetch trade order failed with: {e}")
            raise TryAgain

        return trade

    def __parse_order_status(self, order):
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
            trade = self.__get_trades_for_symbol(order["symbol"])
            if trade:
                data["timestamp"] = trade["timestamp"]
                data["amount"] = float(trade["amount"])
                data["price"] = trade["price"]
                data["orderid"] = trade["order"]
                data["symbol"] = trade["symbol"]
                data["side"] = trade["side"]
                data["amount_fee"] = trade["fee_cost"]
                data["ordersize"] = order["cost"]
            else:
                Exchange.logging.info(
                    f"Getting trades for {order["symbol"]} failed - using information of order."
                )
                data["timestamp"] = order["timestamp"]
                data["amount"] = float(order["amount"])
                data["price"] = order["price"]
                data["orderid"] = order["id"]
                data["symbol"] = order["symbol"]
                data["side"] = order["side"]
                data["amount_fee"] = order["fee"]
                data["ordersize"] = order["cost"]

        return data

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    def __get_amount_from_symbol(self, ordersize, symbol) -> float:
        price = self.__get_price_for_symbol(symbol)
        amount = None
        try:
            amount = self.exchange.amount_to_precision(
                symbol, float(ordersize) / float(price)
            )
        except ccxt.NetworkError as e:
            Exchange.logging.error(
                f"Getting amount for {symbol} failed due to a network error: {e}"
            )
            raise TryAgain
        except ccxt.ExchangeError as e:
            Exchange.logging.error(
                f"Getting amount for {symbol} failed due to an exchange error: {e}"
            )
            raise TryAgain
        except Exception as e:
            Exchange.logging.error(f"Getting amount for {symbol} failed with: {e}")
            raise TryAgain

        return amount

    async def __get_symbols(self):
        data = await Trades.all().distinct().values_list("symbol", flat=True)
        return data

    def __split_symbol(self, pair):
        symbol = pair
        if not "/" in pair:
            pair, currency = pair.split(self.currency)
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
            Exchange.logging.error(f"Error adding trade to database: {e}")
            result = False

        return result

    @retry(stop=stop_after_attempt(3))
    async def __delete_trade(self, order):
        result = False

        try:
            # Delete database entries after trade sell
            await Trades.filter(bot=order["botname"]).delete()
            tickers = await self.__get_symbols()
            # Check if trades has been closed (DirtyFixTry - sometimes trades are still in to DB!)
            if order["symbol"] in tickers:
                Exchange.logging.error(f"Error deleting trade from database. Retrying")
                raise TryAgain
            result = True
        except Exception as e:
            Exchange.logging.error(f"Error deleting trade from database: {e}")
            raise TryAgain

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
                Exchange.logging.info(f"Try to buy {amount} {pair}")
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
            except Exception as e:
                Exchange.logging.error(f"Buying pair {pair} failed with: {e}")
                results = None

        return results

    def __sell(self, amount, pair, position):
        results = None
        order = {}

        if self.dry_run:
            order["symbol"] = True
            time.sleep(0.2)
            results = order
        else:
            try:
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
            except Exception as e:
                Exchange.logging.error(f"Selling pair {pair} failed with: {e}")
                results = None

        return results

    async def __buy_order(self, order):
        trade = self.__buy(order["ordersize"], order["symbol"], order["direction"])

        if trade:
            Exchange.logging.info(f"Opened trade: {trade}")

            order_status = self.__parse_order_status(trade)
            order.update(order_status)
            order["precision"] = self.__get_precision_for_symbol(order_status["symbol"])
            order["amount"] = float(order_status["amount"])
            order["amount_fee"] = 0.0
            order["fees"] = 0.0

            # Substract the order fees
            if not self.fee_deduction:
                order["fees"] = self.exchange.fetch_trading_fee(
                    symbol=order_status["symbol"]
                )["taker"]
                order["amount_fee"] = order["amount"] * float(order["fees"])
                order["amount"] = float(order_status["amount"]) - order["amount_fee"]

                Exchange.logging.debug(
                    f"Fee Deduction not active. Real amount {order_status['amount']}, deducted amount {order['amount']}"
                )

            # Add trade to database and push message to Watcher
            if await self.__add_trade(order):
                # Update tickers for tickers watcher
                tickers = await self.__get_symbols()
                await Exchange.tickers.put(tickers)
            else:
                Exchange.logging.error(
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

        # Sell order to exchange
        trade = self.__sell(amount, order["symbol"], order["direction"])

        # Delete trade from database and push message to Statistics
        if trade:
            Exchange.logging.info(f"Sold {amount} {order['symbol']} on Exchange")
            if await self.__delete_trade(order):
                Exchange.logging.info(
                    f"Removed trades for {order['symbol']} in database"
                )
                # Update statistics
                if not self.dry_run:
                    order_status = self.__parse_order_status(trade)
                    data = {}
                    data["type"] = "sold_check"
                    data["sell"] = True
                    data["symbol"] = order_status["symbol"]
                    data["total_amount"] = order_status["amount"]
                    data["total_cost"] = order["total_cost"]
                    # data["total_cost"] = order_status["ordersize"] --> uses wrong ordersize
                    data["current_price"] = order_status["price"]
                    data["tp_price"] = order_status["price"]
                    data["avg_price"] = data["total_cost"] / data["total_amount"]
                    data["actual_pnl"] = order["actual_pnl"]

                    await Exchange.statistic.put(data)

                # Update tickers for tickers watcher
                tickers = await self.__get_symbols()
                # Not sending empty symbol list (watcher_tickes needs at least one!)
                if tickers:
                    await Exchange.tickers.put(tickers)
            else:
                Exchange.logging.error(
                    "Error deleting trade from database - trade is done on Exchange, but not on Moonwalker Bot"
                )

    async def __process_order(self, data):

        data["symbol"] = self.__split_symbol(data["symbol"])
        data["direction"] = self.__split_direction(data["direction"])

        if data["side"] == "buy":
            await self.__buy_order(data)
            Exchange.logging.info(f"New buy request: {data}")
        if data["side"] == "sell" and "type_sell" in data:
            Exchange.logging.info(f"New sell request: {data}")
            await self.__sell_order(data)

    async def run(self):
        while Exchange.status:
            data = await Exchange.order.get()
            await self.__process_order(data)
            Exchange.order.task_done()

    async def shutdown(self):
        Exchange.status = False
        await self.exchange.close()
