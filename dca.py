from logger import LoggerFactory
from data import Data


class Dca:
    def __init__(
        self,
        dca,
        statistic,
        trailing_tp,
        dynamic_dca,
        dynamic_tp,
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
        self.dynamic_tp = dynamic_tp
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
        self.sl = sl
        self.data = Data(loglevel)

        # Class Attributes
        self.status = True
        self.dca = dca
        self.order = order
        self.statistic = statistic
        self.logging = LoggerFactory.get_logger(
            "logs/dca.log", "dca", log_level=loglevel
        )
        self.logging.info("Initialized")

    def __dynamic_dca_strategy(self, symbol, price):
        result = False

        token, currency = symbol.split("/")
        symbol = f"{token}{currency}"

        result = self.strategy.run(symbol, price)

        return result

    async def __take_profit(self, symbol, current_price):
        trades = await self.data.get_trades(symbol)

        if trades:
            cost = trades["total_cost"]
            fee = trades["fee"]
            total_amount_purchased = trades["total_amount"]
            symbol = trades["symbol"]
            bot_type = trades["direction"]
            bot_name = trades["bot"]
            safety_order_count = trades["safetyorders_count"]
            sell = False

            # Last sell fee has to be considered
            total_cost = cost + (cost * fee)
            average_buy_price = total_cost / total_amount_purchased

            # Calculate static TP-Price
            take_profit_price = average_buy_price * (1 + (self.tp / 100))

            # Calculate dynamic TP-Price
            if self.dynamic_tp > 0:
                effective_take_profit = max(
                    0,
                    self.tp - (safety_order_count * self.dynamic_tp),
                )
                # Calculate the take profit price
                take_profit_price = average_buy_price * (
                    1 + (effective_take_profit / 100)
                )

            stop_loss_price = average_buy_price * (1 - (self.sl / 100))
            if (current_price >= take_profit_price) or (
                current_price <= stop_loss_price
                and self.max_safety_orders == safety_order_count
            ):
                sell = True

            # Actual PNL in percent (value for profit calculation)
            actual_pnl = self.data.calculate_actual_pnl(trades, current_price)

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
                    ) or actual_pnl < self.tp:
                        # self.logging.debug(
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
                    "current_price": current_price,
                }
                # Send new take profit order to exchange module
                self.logging.debug(f"Sending sell order to exchange module: {order}")
                await self.order.put(order)

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
            await self.statistic.put(logging_json)

    async def __dca_strategy(self, symbol, current_price):
        trades = await self.data.get_trades(symbol)

        if trades:
            safety_orders = trades["safetyorders"]
            safety_order_count = trades["safetyorders_count"]
            bo_price = trades["bo_price"]

            # Apply price deviation for the first safety order
            next_so_percentage = self.price_deviation
            bot_type = trades["direction"]
            bot_name = trades["bot"]
            new_so = False
            safety_order_size = self.so

            # Actual PNL in percent
            actual_pnl = self.data.calculate_actual_pnl(trades, current_price)

            # Total PNL from base order
            total_pnl = ((current_price - bo_price) / bo_price) * 100

            # Total deviation from base order
            max_deviation = (self.price_deviation * (1 - self.step_scale ** (safety_order_count+1))) / (1 - self.step_scale)
            max_deviation = round(max_deviation, 2)
            
            # Check if safety orders exist yet
            if safety_orders and self.max_safety_orders:
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

                last_so_price = float(safety_orders[-1]["price"])
            else:
                last_so_price = 0

            # We have not reached the max safety orders
            if self.max_safety_orders and (safety_order_count < self.max_safety_orders):

                if self.dynamic_dca:

                    # Trigger new safety order for dynamic dca
                    if actual_pnl <= -abs(next_so_percentage):

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
                                "order_count": safety_order_count + 1,
                                "ordertype": "market",
                                "so_percentage": next_so_percentage,
                                "side": "buy",
                            }
                            # Send new safety order request to exchange module
                            await self.order.put(order)

                else:

                    # Trigger new safety order for static dca
                    if  total_pnl <= -abs(max_deviation):

                        if safety_order_count == 0:
                            next_so_percentage = -abs(self.price_deviation)
                            new_so = True
                        else:
                            new_so = True

                        if new_so:
                            order = {
                                "ordersize": safety_order_size,
                                "symbol": symbol,
                                "direction": bot_type,
                                "botname": bot_name,
                                "baseorder": False,
                                "safetyorder": True,
                                "order_count": safety_order_count + 1,
                                "ordertype": "market",
                                "so_percentage": next_so_percentage,
                                "side": "buy",
                            }
                            # Send new safety order request to exchange module
                            await self.order.put(order)

                # Logging configuration
                logging_json = {
                    "type": "dca_check",
                    "symbol": symbol,
                    "botname": bot_name,
                    "so_orders": safety_order_count,
                    "last_so_price": last_so_price,
                    "new_so_size": safety_order_size,
                    "price_deviation": next_so_percentage,
                    "actual_pnl": actual_pnl,
                    "new_so": new_so,
                }
                # Send new statistics to statistics module
                await self.statistic.put(logging_json)

    async def run(self):
        while True:
            data = await self.dca.get()

            # New price action for DCA calculation
            if data["type"] == "ticker_price":
                price = data["ticker"]["price"]
                symbol = data["ticker"]["symbol"]

                # Check DCA
                await self.__dca_strategy(symbol, price)

                # Check TP
                await self.__take_profit(symbol, price)

            self.dca.task_done()

    async def shutdown(self):
        self.status = False
