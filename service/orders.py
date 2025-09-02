import helper
import json
import time
from datetime import datetime
from service.trades import Trades
from service.exchange import Exchange

logging = helper.LoggerFactory.get_logger("logs/orders.log", "orders")


class Orders:
    def __init__(self):
        config = helper.Config()
        self.utils = helper.Utils()
        self.exchange = Exchange()
        self.trades = Trades()
        self.currency = config.get("currency").upper()
        self.dynamic_dca = config.get("dynamic_dca", False)

    async def receive_sell_order(self, order):
        logging.info(f"Incoming sell order for {order["symbol"]}")

        order["total_amount"] = await self.trades.get_token_amount_from_trades(
            order["symbol"]
        )

        # 1. Create exchange order
        order_status = await self.exchange.create_spot_market_sell(order)

        if order_status:
            # 2. Create closed trade
            open_timestamp = 0.0
            base_order = await self.trades.get_trade_by_ordertype(
                order_status["symbol"], baseorder=True
            )

            try:
                open_timestamp = float(base_order[0]["timestamp"])
            except Exception as e:
                open_timestamp = datetime.timestamp(datetime.now())
                logging.debug(
                    f"Did not found a timestamp - taking default value. Cause {e}"
                )
                pass

            # 3. Delete trade
            await self.trades.delete_trades(order["symbol"])

            open_trade = await self.trades.get_open_trades_by_symbol(
                order_status["symbol"]
            )
            # ToDo - why is it sometimes emtpy? Race condition?
            so_count = 0
            if open_trade:
                so_count = open_trade[0]["so_count"]

            sell_timestamp = time.mktime(datetime.now().timetuple()) * 1000
            sell_date = datetime.now()
            open_date = datetime.fromtimestamp((open_timestamp / 1000.0))

            # Calculate trade duration
            duration_data = self.__calculate_trade_duration(
                open_timestamp, sell_timestamp
            )
            payload = {
                "symbol": order_status["symbol"],
                "so_count": so_count,
                "profit": order_status["profit"],
                "profit_percent": order_status["profit_percent"],
                "amount": order_status["total_amount"],
                "cost": order_status["total_cost"],
                "tp_price": order_status["tp_price"],
                "avg_price": order_status["avg_price"],
                "open_date": open_date,
                "close_date": sell_date,
                "duration": duration_data,
            }
            await self.trades.create_closed_trades(payload)

            # 4. Delete Open trades
            await self.trades.delete_open_trades(order["symbol"])

            # 5. Delete old ticker data
            await self.trades.delete_ticker_data_for_trades(order["symbol"])
        else:
            logging.error(f"Failed creating sell order for {order["symbol"]}")

    async def receive_buy_order(self, order):

        logging.info(f"Incoming buy order for {order["symbol"]}")

        # 1. Create exchange order
        order_status = await self.exchange.create_spot_market_buy(order)

        if order_status:
            # 2. Create trade
            payload = {
                "timestamp": order_status["timestamp"],
                "ordersize": order_status["ordersize"],
                "fee": order_status["fees"],
                "precision": order_status["precision"],
                "amount_fee": order_status["amount_fee"],
                "amount": order_status["amount"],
                "price": order_status["price"],
                "symbol": order_status["symbol"],
                "orderid": order_status["orderid"],
                "bot": order_status["botname"],
                "ordertype": order_status["ordertype"],
                "baseorder": order_status["baseorder"],
                "safetyorder": order_status["safetyorder"],
                "order_count": order_status["order_count"],
                "so_percentage": order_status["so_percentage"],
                "direction": order_status["direction"],
                "side": order_status["side"],
            }
            await self.trades.create_trades(payload)

            # 3. Create open trade (only for base order)
            if not order["safetyorder"]:
                payload = {"symbol": order_status["symbol"]}
                await self.trades.create_open_trades(payload)
        else:
            logging.error(f"Failed creating buy order for {order["symbol"]}")

    async def receive_stop_signal(self, symbol):
        logging.info("Incoming stop order")
        symbol = symbol.upper()
        token, currency = symbol.split("-")
        symbol = f"{token}/{currency}"
        if await self.trades.stop_trade(symbol):
            return True
        else:
            logging.error(f"Cannot stop trade for {symbol}. See trade logs for errors.")
        return False

    async def receive_sell_signal(self, symbol):
        symbol = symbol.upper()
        token, currency = symbol.split("-")
        symbol = f"{token}/{currency}"
        trades = await self.trades.get_trades_for_orders(symbol)
        actual_pnl = self.utils.calculate_actual_pnl(trades, trades["current_price"])

        if trades:
            actual_pnl = self.utils.calculate_actual_pnl(trades)

            order = {
                "symbol": trades["symbol"],
                "direction": trades["direction"],
                "side": "sell",
                "type_sell": "order_sell",
                "actual_pnl": actual_pnl,
                "total_cost": trades["total_cost"],
                "current_price": trades["current_price"],
            }

            await self.receive_sell_order(order)
            return True

        # If OpenTrade remove hasn't worked
        else:
            logging.error(
                f"Force remove trade from OpenTrades table for {symbol} - No running trade found."
            )
            await self.trades.delete_open_trades(symbol)
            return False

    async def receive_buy_signal(self, symbol, ordersize):
        symbol = symbol.upper()
        token, currency = symbol.split("-")
        symbol = f"{token}/{currency}"
        trades = await self.trades.get_trades_for_orders(symbol)

        if trades:
            actual_pnl = self.utils.calculate_actual_pnl(trades)
            if trades["safetyorders"]:
                safety_order_count = len(trades["safetyorders"])
            else:
                safety_order_count = 0

            order = {
                "ordersize": ordersize,
                "symbol": symbol,
                "direction": trades["direction"],
                "botname": trades["bot"],
                "baseorder": False,
                "safetyorder": True,
                "order_count": safety_order_count + 1,
                "ordertype": "market",
                "so_percentage": actual_pnl,
                "side": "buy",
            }

            await self.receive_buy_order(order)
            return True
        else:
            return False

    def __calculate_trade_duration(self, start_date, end_date):
        # Convert Unix timestamps to datetime objects
        date1 = datetime.fromtimestamp((start_date / 1000.0))
        date2 = datetime.fromtimestamp(end_date / 1000.0)

        # Calculate the time difference
        time_difference = date2 - date1

        # Extract days, seconds, and microseconds
        days = time_difference.days
        seconds = time_difference.seconds

        # Calculate hours, minutes, and seconds
        hours, reminder = divmod(seconds, 3600)
        minutes, seconds = divmod(reminder, 60)

        return json.dumps(
            {
                "days": days,
                "hours": hours,
                "minutes": minutes,
                "seconds": seconds,
            }
        )
