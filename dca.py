import requests
from logger import LoggerFactory
from models import Trades
from tortoise.models import Q


class Dca:
    def __init__(
        self,
        dca,
        statistic,
        trailing_tp,
        dynamic_dca,
        strategy,
        order,
        volume_scale,
        step_scale,
        max_safety_orders,
        price_deviation,
        so,
        tp,
        sl,
        max_active,
        ws_url,
        loglevel,
        market,
    ):
        self.trailing_tp = trailing_tp
        self.dynamic_dca = dynamic_dca
        self.strategy = strategy
        self.volume_scale = volume_scale
        self.step_scale = step_scale
        self.max_safety_orders = max_safety_orders
        self.price_deviation = price_deviation
        self.so = so
        self.max_active = max_active
        self.ws_url = ws_url
        self.market = market
        self.pnl = 0.0

        # Class Attributes
        Dca.tp = tp
        if not sl:
            sl = 10000
        Dca.sl = sl
        Dca.dca = dca
        Dca.order = order
        Dca.statistic = statistic
        Dca.logging = LoggerFactory.get_logger("dca.log", "dca", log_level=loglevel)
        Dca.logging.info("Initialized")

    async def __get_trades(self, field, value):
        if field == "symbol":
            trades = await Trades.filter(symbol=value).values()
        elif field == "orderid":
            trades = await Trades.filter(orderid=value).values()
        if trades:
            return trades[0]

    def __dynamic_dca_strategy(self, symbol, price):
        result = False

        token, currency = symbol.split("/")
        symbol = f"{token}{currency}"

        result = self.strategy.run(symbol, price)

        return result

    async def __take_profit(self, symbol, current_price):
        tp_percentage = Dca.tp
        sl_percentage = Dca.sl
        buy_orders = await Trades.filter(symbol=symbol).values()
        if buy_orders:
            cost = 0.0
            future_amount = 0.0
            total_amount_purchased = 0.0
            take_profit_price = 0.0
            average_buy_price = 0.0
            symbol = buy_orders[-1]["symbol"]
            bot_type = buy_orders[-1]["direction"]
            bot_name = buy_orders[-1]["bot"]
            fee = buy_orders[-1]["fee"]
            sell = False

            # Calculate total_investment
            for order in buy_orders:
                price = float(order["price"])
                amount = float(order["amount"])
                amount_fee = float(order["amount_fee"])
                # cost += price * (amount + amount_fee)
                cost += float(order["ordersize"])
                total_amount_purchased += amount + amount_fee
                future_amount += amount

            # Last sell fee has to be considered
            total_cost = cost + (cost * fee)

            # Precision has to be considered - for high precision coins
            # if buy_orders[-1]["precision"] == 0:
            #     average_buy_price = total_cost / (total_amount_purchased - 1)
            #     display_buy_price = cost / (display_amount - 1)
            # else:
            #     average_buy_price = total_cost / total_amount_purchased
            #     display_buy_price = cost / display_amount
            if self.market == "future":
                average_buy_price = cost / future_amount
            else:
                average_buy_price = total_cost / total_amount_purchased

            # Calculate TP-Price
            if bot_type == "short":
                take_profit_price = average_buy_price * (1 - (tp_percentage / 100))
                stop_loss_price = average_buy_price * (1 + (sl_percentage / 100))
                if (
                    current_price <= take_profit_price
                    or current_price >= stop_loss_price
                ):
                    sell = True
            else:
                take_profit_price = average_buy_price * (1 + (tp_percentage / 100))
                stop_loss_price = average_buy_price * (1 - (sl_percentage / 100))
                if (
                    current_price >= take_profit_price
                    or current_price <= stop_loss_price
                ):
                    sell = True

            # Actual PNL in percent (value for profit calculation)
            actual_pnl = ((current_price - average_buy_price) / average_buy_price) * 100

            if bot_type == "short" and actual_pnl < 0:
                actual_pnl = abs(actual_pnl)
            else:
                actual_pnl = -abs(actual_pnl)

            self.logging.debug(
                f"current price: {current_price}, buy_price: {average_buy_price} = PNL: {actual_pnl}, Sell: {sell}"
            )

            # Trailing TP
            if self.trailing_tp > 0:
                if (sell and actual_pnl != self.pnl) and self.pnl != 0:
                    diff = actual_pnl - self.pnl
                    diff_percentage = (diff / self.pnl) * 100
                    self.logging.debug(
                        f"TTP Check: {symbol} - PNL Difference: {diff_percentage}, Actual PNL: {actual_pnl}, DCA-PNL: {self.pnl}"
                    )
                    # Sell if trailing deviation is reached or actual PNL is under minimum TP
                    if (
                        diff_percentage < 0 and abs(diff_percentage) > self.trailing_tp
                    ) or actual_pnl < Dca.tp:
                        # self.logging.debug(
                        #     f"TTP Check: {symbol} - Percentage decrease - Take profit: {diff_percentage}"
                        # )
                        sell = True
                    else:
                        sell = False
                        self.pnl = actual_pnl
                else:
                    self.pnl = actual_pnl

            # Logging configuration
            logging_json = {
                "type": "tp_check",
                "symbol": symbol,
                "botname": bot_name,
                "total_cost": cost,
                "total_amount": total_amount_purchased,
                "current_price": current_price,
                "avg_price": average_buy_price,
                "tp_price": take_profit_price,
                "actual_pnl": actual_pnl,
                "sell": sell,
                "direction": bot_type,
            }

            # TP reached - sell order
            if sell:
                order = {
                    "symbol": symbol,
                    "direction": bot_type,
                    "botname": bot_name,
                    "side": "sell",
                    "type_sell": "order_sell",
                }
                await Dca.order.put(order)
            await Dca.statistic.put(logging_json)

    async def __dca_strategy(self, symbol, current_price):
        # Initialize variables
        base_order = await Trades.filter(
            Q(baseorder__gt=0), Q(symbol=symbol), join_type="AND"
        ).values()
        if base_order:
            safety_orders = await Trades.filter(
                Q(safetyorder__gt=0), Q(symbol=symbol), join_type="AND"
            ).values()

            safety_order_iterations = 0
            # Apply price deviation for the first safety order
            next_so_percentage = self.price_deviation
            bot_type = base_order[0]["direction"]
            bot_name = base_order[0]["bot"]
            bo_price = float(base_order[0]["price"])
            last_price = 0
            new_so = False

            # Check if safety orders exist yet
            if safety_orders and self.max_safety_orders:
                safety_order_size = self.so
                safety_order_iterations = len(safety_orders)

                # print(safety_orders)
                safety_order_size = safety_orders[-1]["ordersize"] * self.volume_scale
                next_so_percentage = float(safety_orders[-1]["so_percentage"]) * float(
                    self.step_scale
                )
                if len(safety_orders) >= 2:
                    next_so_percentage = next_so_percentage + float(
                        safety_orders[-2]["so_percentage"]
                    )
                else:
                    next_so_percentage = next_so_percentage + self.price_deviation

                last_price = float(safety_orders[-1]["price"])

            price_change_percentage = ((current_price - bo_price) / bo_price) * 100

            if price_change_percentage > 0:
                price_change_percentage = -abs(price_change_percentage)
            else:
                price_change_percentage = abs(price_change_percentage)

            # We have not reached the max safety orders
            if (
                self.max_safety_orders
                and safety_order_iterations < self.max_safety_orders
            ):
                # Trigger new safety order
                if price_change_percentage >= next_so_percentage:
                    # Dynamic safety orders
                    if self.dynamic_dca and self.__dynamic_dca_strategy(
                        symbol, current_price
                    ):
                        # Set next_so_percentage to current percentage
                        next_so_percentage = price_change_percentage
                        new_so = True
                    else:
                        new_so = False

                    if new_so:
                        order = {
                            "ordersize": safety_order_size,
                            "symbol": symbol,
                            "direction": bot_type,
                            "botname": bot_name,
                            "baseorder": False,
                            "safetyorder": True,
                            "order_count": safety_order_iterations + 1,
                            "ordertype": "market",
                            "so_percentage": next_so_percentage,
                            "side": "buy",
                        }
                        await Dca.order.put(order)

                # Logging configuration
                logging_json = {
                    "type": "dca_check",
                    "symbol": symbol,
                    "botname": bot_name,
                    "so_orders": safety_order_iterations,
                    "last_so_price": last_price,
                    "new_so_size": safety_order_size,
                    "price_deviation": next_so_percentage,
                    "actual_deviation": price_change_percentage,
                    "new_so": new_so,
                }

                await Dca.statistic.put(logging_json)

    async def __open_market_order(self, orderid, order_type, order_count):
        Dca.logging.debug("Creating market order, because DCA triggered!")

    async def __open_limit_orders(self, orderid, order_type, order_count):
        Dca.logging.debug(
            f"Active safety orders enabled. Creating {self.max_active} limit orders for orderid {orderid}."
        )
        if order_type == "baseorder":
            Dca.logging.debug(f"Place first {self.max_active} limit safety orders")
        elif order_type == "safetyorder":
            if order_count < self.max_safety_orders:
                Dca.logging.debug(f"Place additional limit safety orders")

    async def __process_dca_signal(self, data):
        # New price action for DCA calculation
        if data["type"] == "ticker_price":
            price = data["ticker"]["price"]
            symbol = data["ticker"]["symbol"]

            # Check DCA
            if self.max_active == 0:
                await self.__dca_strategy(symbol, price)

            # Check TP
            await self.__take_profit(symbol, price)

        # New order (for active safety orders)
        elif data["type"] == "new_order" and self.max_active != 0:
            orderid = data["order"]["orderid"]
            Dca.logging.debug(
                f"Got new order for symbol {data['order']['symbol']} with orderid {orderid}"
            )

            trade = await self.__get_trades("orderid", orderid)
            if trade:
                # New baseorder has been placed - ready for new open limit orders
                if trade["baseorder"]:
                    Dca.logging.debug("New baseorder placed - setting SO limit orders!")
                    # Open first limit orders (if activated)
                    await self.__open_limit_orders(orderid, "baseorder", 1)

                # New opened safetyorder - nothing to do
                elif trade["safetyorder"] and data["order"]["status"] == "open":
                    Dca.logging.debug("New safetyorder successfully set.")

                # Limit order reached - ready to open new limit orders
                elif trade["safetyorder"] and data["order"]["status"] == "closed":
                    # New Safetyorder came from this modul - just spit out information - nothing to do.
                    Dca.logging.debug("Existing safetyorder filled.")
                    await self.__open_limit_orders(
                        orderid, "safetyorder", trade["order_count"]
                    )
                # Closed baseorder or other...
                else:
                    Dca.logging.debug(trade)
            else:
                Dca.logging.debug("Order was a sell order - nothing to do.")

    async def run(self):
        while True:
            data = await Dca.dca.get()
            await self.__process_dca_signal(data)
