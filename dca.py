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
        self.ws_url = ws_url
        self.market = market
        self.pnl = 0.0
        self.tp = tp
        if not sl:
            sl = 10000
        self.sl = sl

        # Class Attributes
        Dca.status = True
        Dca.dca = dca
        Dca.order = order
        Dca.statistic = statistic
        Dca.logging = LoggerFactory.get_logger(
            "logs/dca.log", "dca", log_level=loglevel
        )
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

    async def __calc_pnl(self, buy_orders, current_price):
        fee = buy_orders[-1]["fee"]
        cost = 0.0
        total_amount_purchased = 0.0

        if buy_orders:
            for order in buy_orders:
                amount = float(order["amount"])
                amount_fee = float(order["amount_fee"])
                cost += float(order["ordersize"])
                total_amount_purchased += amount + amount_fee

            # Last sell fee has to be considered
            total_cost = cost + (cost * fee)

            # Calculate average buy price
            average_buy_price = total_cost / total_amount_purchased

            actual_pnl = ((current_price - average_buy_price) / average_buy_price) * 100

            return actual_pnl
        else:
            Dca.logging.error("No actual buy orders.")

    async def __take_profit(self, symbol, current_price, buy_orders):
        tp_percentage = self.tp
        sl_percentage = self.sl
        if buy_orders:
            cost = 0.0
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
                amount = float(order["amount"])
                amount_fee = float(order["amount_fee"])
                cost += float(order["ordersize"])
                total_amount_purchased += amount + amount_fee

            # Last sell fee has to be considered
            total_cost = cost + (cost * fee)

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
            actual_pnl = await self.__calc_pnl(buy_orders, current_price)

            # Trailing TP
            if self.trailing_tp > 0:
                if (sell and actual_pnl != self.pnl) and self.pnl != 0:
                    diff = actual_pnl - self.pnl
                    diff_percentage = (diff / self.pnl) * 100
                    Dca.logging.debug(
                        f"TTP Check: {symbol} - PNL Difference: {diff_percentage}, Actual PNL: {actual_pnl}, DCA-PNL: {self.pnl}"
                    )
                    # Sell if trailing deviation is reached or actual PNL is under minimum TP
                    if (
                        diff_percentage < 0 and abs(diff_percentage) > self.trailing_tp
                    ) or actual_pnl < self.tp:
                        # Dca.logging.debug(
                        #     f"TTP Check: {symbol} - Percentage decrease - Take profit: {diff_percentage}"
                        # )
                        sell = True
                    else:
                        sell = False
                        self.pnl = actual_pnl
                else:
                    self.pnl = actual_pnl

            # TP reached - sell order (market)
            if sell:
                order = {
                    "symbol": symbol,
                    "direction": bot_type,
                    "botname": bot_name,
                    "side": "sell",
                    "type_sell": "order_sell",
                    "actual_pnl": actual_pnl,
                    "total_cost": cost,
                }
                # Send new take profit order to exchange module
                self.logging.debug(f"Sending sell order to exchange module: {order}")
                await Dca.order.put(order)

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
            await Dca.statistic.put(logging_json)

    async def __dca_strategy(self, symbol, current_price, buy_orders):
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
            safety_order_size = self.so

            # Check if safety orders exist yet
            if safety_orders and self.max_safety_orders:
                safety_order_iterations = len(safety_orders)
                safety_order_size = safety_orders[-1]["ordersize"] * self.volume_scale
                next_so_percentage = float(safety_orders[-1]["so_percentage"]) * float(
                    self.step_scale
                )
                if len(safety_orders) >= 2:
                    next_so_percentage = -abs(next_so_percentage) + -abs(
                        float(safety_orders[-2]["so_percentage"])
                    )
                else:
                    next_so_percentage = -abs(next_so_percentage) + -abs(
                        self.price_deviation
                    )

                last_price = float(safety_orders[-1]["price"])

            # Actual PNL in percent
            actual_pnl = await self.__calc_pnl(buy_orders, current_price)

            # We have not reached the max safety orders
            if (
                self.max_safety_orders
                and safety_order_iterations < self.max_safety_orders
            ):
                # Trigger new safety order
                if actual_pnl <= -abs(next_so_percentage):
                    # Dynamic safety orders
                    if self.dynamic_dca and self.__dynamic_dca_strategy(
                        symbol, current_price
                    ):
                        # Set next_so_percentage to current percentage
                        next_so_percentage = actual_pnl
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
                        # Send new safety order request to exchange module
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
                    "actual_pnl": actual_pnl,
                    "new_so": new_so,
                }
                # Send new DCA statistics to statistics module
                await Dca.statistic.put(logging_json)

    async def __process_dca_signal(self, data):
        # New price action for DCA calculation
        if data["type"] == "ticker_price":
            price = data["ticker"]["price"]
            symbol = data["ticker"]["symbol"]

            # Get buy orders from db for calculations
            buy_orders = await Trades.filter(symbol=symbol).values()

            # Check DCA
            await self.__dca_strategy(symbol, price, buy_orders)

            # Check TP
            await self.__take_profit(symbol, price, buy_orders)

    async def run(self):
        while True:
            data = await Dca.dca.get()
            await self.__process_dca_signal(data)
            Dca.dca.task_done()

    async def shutdown(self):
        Dca.status = False
