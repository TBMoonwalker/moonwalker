import requests
from logger import LoggerFactory
from models import Trades
from tortoise.models import Q


class Dca:
    def __init__(
        self,
        dca,
        dynamic_tp,
        dynamic_dca,
        order,
        volume_scale,
        step_scale,
        max_safety_orders,
        price_deviation,
        so,
        tp,
        max_active,
        ws_url,
        loglevel,
    ):
        self.dynamic_tp = dynamic_tp
        self.dynamic_dca = dynamic_dca
        self.volume_scale = volume_scale
        self.step_scale = step_scale
        self.max_safety_orders = max_safety_orders
        self.price_deviation = price_deviation
        self.so = so
        self.tp = tp
        self.max_active = max_active
        self.ws_url = ws_url

        # Class Attributes
        Dca.dca = dca
        Dca.order = order
        Dca.logging = LoggerFactory.get_logger("dca.log", "dca", log_level=loglevel)
        Dca.logging.info("Initialized")

    async def __get_trades(self, field, value):
        if field == "symbol":
            trades = await Trades.filter(symbol=value).values()
        elif field == "orderid":
            trades = await Trades.filter(orderid=value).values()
        if trades:
            return trades[0]

    def __dynamic_dca_strategy(self, symbol):
        ema_cross_request = requests.get(f"{self.ws_url}/indicators/ema_cross/{symbol}")
        ema_cross_response = ema_cross_request.json()
        if ema_cross_response == "down":
            # avoid SO order
            return False
        else:
            return True

    async def __take_profit(self, symbol, tp_percentage, current_price):
        buy_orders = await Trades.filter(symbol=symbol).values()
        if buy_orders:
            total_cost = 0.0
            total_amount_purchased = 0.0
            symbol = buy_orders[-1]["symbol"]
            bot_type = buy_orders[-1]["direction"]
            bot_name = buy_orders[-1]["bot"]
            sell = False

            # Calculate total_investment
            for order in buy_orders:
                price = float(order["price"])
                amount = float(order["amount"])
                total_cost += price * amount
                total_amount_purchased += amount

            average_buy_price = total_cost / total_amount_purchased

            # Calculate TP-Price
            if bot_type == "short":
                take_profit_price = average_buy_price * (1 - (tp_percentage / 100))
                if current_price <= take_profit_price:
                    sell = True
            else:
                take_profit_price = average_buy_price * (1 + (tp_percentage / 100))
                if current_price >= take_profit_price:
                    sell = True

            # Actual PNL in percent
            actual_pnl = ((current_price - average_buy_price) / average_buy_price) * 100

            # Logging configuration
            logging_json = {
                "symbol": symbol,
                "botname": bot_name,
                "total_cost": total_cost,
                "total_amount": total_amount_purchased,
                "current_price": current_price,
                "avg_price": round(average_buy_price, 4),
                "tp_price": round(take_profit_price, 4),
                "actual_pnl": round(actual_pnl, 2),
                "sell": sell,
            }

            # TP reached - sell order
            if sell:
                order = {
                    "symbol": symbol,
                    "direction": bot_type,
                    "botname": bot_name,
                    "side": "sell",
                }
                await Dca.order.put(order)
                Dca.logging.info(f"TP Sell: {logging_json}")

            Dca.logging.debug(f"TP Check: {logging_json}")

    async def __dca_strategy(self, symbol, current_price):
        # Initialize variables
        base_order = await Trades.filter(
            Q(baseorder__gt=0), Q(symbol=symbol), join_type="AND"
        ).values()
        if base_order:
            safety_orders = await Trades.filter(
                Q(safetyorder__gt=0), Q(symbol=symbol), join_type="AND"
            ).values()

            safety_order_size = self.so
            safety_order_iterations = 0
            # Apply price deviation for the first safety order
            next_so_percentage = self.price_deviation
            bot_type = base_order[0]["direction"]
            bot_name = base_order[0]["bot"]
            last_price = float(base_order[0]["price"])
            new_so = False

            # Check if safety orders exist yet
            if safety_orders:
                safety_order_iterations = len(safety_orders)

                safety_order_size = safety_orders[-1]["ordersize"] * self.volume_scale
                next_so_percentage = (
                    float(safety_orders[-1]["so_percentage"]) * self.step_scale
                )
                last_price = float(safety_orders[-1]["price"])

                # Dynamic TP
                if self.dynamic_tp:
                    safety_order_threshold = self.max_safety_orders * 0.75
                    if safety_order_iterations >= safety_order_threshold:
                        # ToDo - make it configurable
                        self.tp = 0.5

            price_change_percentage = ((current_price - last_price) / last_price) * 100

            # Logging configuration
            logging_json = {
                "symbol": symbol,
                "botname": bot_name,
                "so_orders": safety_order_iterations,
                "last_price": last_price,
                "new_so_size": safety_order_size,
                "price_deviation": next_so_percentage,
                "actual_deviation": round(price_change_percentage, 2),
                "new_so": new_so,
            }

            # We have not reached the max safety orders
            if safety_order_iterations < self.max_safety_orders:
                # Check if new safety order is necessary
                if bot_type == "long":
                    price_change_percentage = abs(price_change_percentage)

                # Trigger new safety order
                if price_change_percentage >= next_so_percentage:
                    # Dynamic safety orders
                    if self.dynamic_dca:
                        if self.__dynamic_dca_strategy(symbol):
                            # ToDo
                            new_so = True
                    else:
                        new_so = True

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
                    Dca.logging.info(f"SO Buy: {logging_json}")

            Dca.logging.debug(f"DCA Check: {logging_json}")

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
            # symbol = data["ticker"]["symbol"].split(":")
            symbol = data["ticker"]["symbol"]

            # Check DCA
            if self.max_active == 0:
                # await self.__dca_strategy(symbol[0], price)
                await self.__dca_strategy(symbol, price)

            # Check TP
            # await self.__take_profit(symbol[0], self.tp, price)
            await self.__take_profit(symbol, self.tp, price)

        # New order (for active safety orders)
        elif data["type"] == "new_order" and self.max_active != 0:
            orderid = data["order"]["orderid"]
            Dca.logging.debug(
                f"Got new order for symbol {data['order']['symbol']} with orderid {orderid}"
            )

            trade = await self.__get_trades("orderid", orderid)
            if trade:
                # New baseorder - ready for new open limit orders
                if trade["baseorder"]:
                    Dca.logging.debug(f"New baseorder!")
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
