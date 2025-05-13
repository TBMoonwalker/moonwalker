import ccxt as ccxt
import decimal
import uuid
import time
import helper
from datetime import datetime
from tenacity import retry, TryAgain, stop_after_attempt, wait_fixed

logging = helper.LoggerFactory.get_logger("logs/exchange.log", "exchange")


class Exchange:
    def __init__(
        self,
    ):
        config = helper.Config()
        self.dry_run = config.get("dry_run", True)
        self.utils = helper.Utils()
        self.currency = config.get("currency").upper()
        self.dry_run = config.get("dry_run", True)
        self.fee_deduction = config.get("fee_deduction", False)
        self.order_check_range = config.get("order_check_range", 5)

        # Exchange configuration
        login_params = {
            "apiKey": config.get("key"),
            "secret": config.get("secret"),
        }
        exchange = config.get("exchange")
        self.exchange_id = exchange
        self.exchange_class = getattr(ccxt, self.exchange_id)
        if self.exchange_id == "okx":
            login_params.update({"password": config.get("password", None)})
        self.exchange = self.exchange_class(login_params)
        self.exchange.set_sandbox_mode(config.get("sandbox", False))
        self.exchange.options["defaultType"] = config.get("market", "spot")
        self.exchange.enableRateLimit = True
        self.exchange.load_markets()
        self.status = True
        Exchange.sell_retry_count = 0

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
            logging.error(
                f"Fetching ticker messages failed due to an exchange error: {e}"
            )
            raise TryAgain
        except ccxt.NetworkError as e:
            logging.error(
                f"Fetching ticker messages failed due to a network error: {e}"
            )
            raise TryAgain
        except Exception as e:
            logging.error(f"Fetching ticker messages failed with: {e}")
            raise TryAgain

        return result

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    def __get_precision_for_symbol(self, pair):

        result = None

        try:
            market = self.exchange.market(pair)
            result = market["precision"]["amount"]
        except ccxt.ExchangeError as e:
            logging.error(f"Fetching market data failed due to an exchange error: {e}")
            raise TryAgain
        except ccxt.NetworkError as e:
            logging.error(f"Fetching market data failed due to a network error: {e}")
            raise TryAgain
        except Exception as e:
            logging.error(f"FFetching market data failed failed with: {e}")
            raise TryAgain

        return result

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(10))
    def __get_trades_for_symbol(self, symbol, orderid):
        trade = None
        time.sleep(1)
        since = self.exchange.milliseconds() - (
            self.order_check_range * 1000
        )  # X seconds from now
        try:
            trade = {}
            amount = 0.0
            fee = 0.0
            cost = 0.0
            orderlist = self.exchange.fetch_my_trades(symbol, since)
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
        except Exception as e:
            logging.error(f"Fetch trade order failed with: {e}")
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
            data["total_amount"] = order["amount"]
        else:
            trade = self.__get_trades_for_symbol(order["symbol"], order["id"])
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
                data["price"] = order["price"]
                data["orderid"] = order["id"]
                data["symbol"] = order["symbol"]
                data["side"] = order["side"]
                data["amount_fee"] = order["fee"]
                data["ordersize"] = order["cost"]

        return data

    @retry(wait=wait_fixed(1), stop=stop_after_attempt(10))
    def __get_amount_from_symbol(self, ordersize, symbol) -> float:
        price = self.__get_price_for_symbol(symbol)
        amount = None
        try:
            amount = self.exchange.amount_to_precision(
                symbol, float(ordersize) / float(price)
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
        except Exception as e:
            logging.error(f"Getting amount for {symbol} failed with: {e}")
            raise TryAgain

        return amount

    async def create_spot_market_buy(self, order):
        order["amount"] = self.__get_amount_from_symbol(
            order["ordersize"], order["symbol"]
        )
        order["price"] = self.__get_price_for_symbol(order["symbol"])

        if self.dry_run:
            order["info"] = {}
            order["info"]["orderId"] = uuid.uuid4()
            order["timestamp"] = time.mktime(datetime.now().timetuple()) * 1000
            time.sleep(0.2)
        else:
            try:
                logging.info(f"Try to buy {order["amount"]} {order["symbol"]}")
                parameter = {}
                trade = self.exchange.create_order(
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
                    f"Buying pair {order["symbol"]} failed due to an exchange error: {e}"
                )
            except ccxt.NetworkError as e:
                logging.error(
                    f"Buying pair {order["symbol"]} failed due to an network error: {e}"
                )
            except Exception as e:
                logging.error(f"Buying pair {order["symbol"]} failed with: {e}")

        logging.info(f"Opened trade: {order}")

        order_status = self.__parse_order_status(order)
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

            logging.debug(
                f"Fee Deduction not active. Real amount {order_status['amount']}, deducted amount {order['amount']}"
            )

        return order

    @retry(wait=wait_fixed(1), stop=stop_after_attempt(100))
    async def create_spot_market_sell(self, order):
        order["info"] = {}

        if self.dry_run:
            order["side"] = order["direction"]
            order["timestamp"] = time.mktime(datetime.now().timetuple()) * 1000
            order["amount"] = order["total_amount"]
            order["info"]["orderId"] = uuid.uuid4()
            order["price"] = order["current_price"]
            time.sleep(0.2)
        else:
            try:
                # Implement sell safeguard, if we cannot sell full amount
                if Exchange.sell_retry_count > 0:
                    decimal_places = abs(
                        decimal.Decimal(str(order["total_amount"])).as_tuple().exponent
                    )
                    reduce_amount = Exchange.sell_retry_count * (10**-decimal_places)
                    order["total_amount"] = order["total_amount"] - reduce_amount
                    logging.info(
                        f"Reducing amount for sell to: {order["total_amount"]}"
                    )

                trade = self.exchange.create_market_sell_order(
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
                        f"Trying to sell {order["total_amount"]} of pair {order["symbol"]} failed due insufficient balance."
                    )
                    Exchange.sell_retry_count += 1
                    raise TryAgain
                else:
                    logging.error(
                        f"Selling pair {order["symbol"]} failed due to an exchange error: {e}"
                    )

            except ccxt.NetworkError as e:
                logging.error(
                    f"Selling pair {order["symbol"]} failed due to an network error: {e}"
                )
            except Exception as e:
                logging.error(f"Selling pair {order["symbol"]} failed with: {e}")

        logging.info(f"Sold {order["total_amount"]} {order['symbol']} on Exchange.")

        order_status = self.__parse_order_status(order)
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
