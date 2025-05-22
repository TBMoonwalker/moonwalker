import helper
import importlib
from service.autopilot import Autopilot
from service.statistic import Statistic
from service.orders import Orders
from service.trades import Trades

logging = helper.LoggerFactory.get_logger("logs/dca.log", "dca")


class Dca:
    def __init__(self):

        self.autopilot = Autopilot()
        self.orders = Orders()
        self.statistic = Statistic()
        self.trades = Trades()
        self.utils = helper.Utils()
        config = helper.Config()

        # Import configured strategies
        dca_strategy_plugin = None
        if config.get("dca_strategy", None):
            dca_strategy = importlib.import_module(
                f"strategies.{config.get('dca_strategy')}"
            )
            dca_strategy_plugin = dca_strategy.Strategy(
                timeframe=config.get("dca_strategy_timeframe", "1m")
            )
        self.config = config
        self.strategy = dca_strategy_plugin
        self.trailing_tp = config.get("trailing_tp", 0)
        self.dynamic_dca = config.get("dynamic_dca", False)
        self.dynamic_tp = config.get("dynamic_tp", 0)
        self.volume_scale = config.get("os")
        self.step_scale = config.get("ss")
        self.max_safety_orders = config.get("mstc", None)
        self.so = config.get("so", None)
        self.price_deviation = config.get("sos", None)
        self.market = config.get("market", "spot")
        Dca.pnl = {}

    def __dynamic_dca_strategy(self, symbol):
        result = False

        token, currency = symbol.split("/")
        symbol = f"{token}{currency}"

        if self.strategy:
            result = self.strategy.run(symbol)

        return result

    async def __calculate_tp(self, current_price, trades):
        if trades:
            sell = False

            # Last sell fee has to be considered
            total_cost = trades["total_cost"] + (trades["total_cost"] * trades["fee"])
            average_buy_price = total_cost / trades["total_amount"]

            # Calculate static TP-Price
            take_profit_price = average_buy_price * (1 + (self.tp / 100))

            # Calculate dynamic TP-Price
            if self.dynamic_tp > 0:
                effective_take_profit = max(
                    0,
                    self.tp - (trades["safetyorders_count"] * self.dynamic_tp),
                )
                # Calculate the take profit price
                take_profit_price = average_buy_price * (
                    1 + (effective_take_profit / 100)
                )

            stop_loss_price = average_buy_price * (1 - (self.sl / 100))
            if (current_price >= take_profit_price) or (
                current_price <= stop_loss_price
                and self.max_safety_orders == trades["safetyorders_count"]
            ):
                sell = True

            # Actual PNL in percent (value for profit calculation)
            actual_pnl = self.utils.calculate_actual_pnl(trades, current_price)

            # Trailing TP
            if self.trailing_tp > 0:
                if sell:
                    if not trades["symbol"] in Dca.pnl:
                        Dca.pnl[trades["symbol"]] = 0.0

                    if (
                        actual_pnl != Dca.pnl[trades["symbol"]]
                        and Dca.pnl[trades["symbol"]] != 0.0
                    ):
                        diff = actual_pnl - Dca.pnl[trades["symbol"]]
                        logging.debug(
                            f"TTP Check: {trades["symbol"]} - PNL Difference: {diff}, Actual PNL: {actual_pnl}, DCA-PNL: {Dca.pnl[trades["symbol"]]}"
                        )
                        # Sell if trailing deviation is reached or actual PNL is under minimum TP
                        if (
                            diff < 0 and abs(diff) > self.trailing_tp
                        ) or actual_pnl < self.tp:
                            # logging.debug(
                            #     f"TTP Check: {symbol} - Percentage decrease - Take profit: {diff_percentage}"
                            # )
                            sell = True
                            Dca.pnl.pop(trades["symbol"])
                        else:
                            sell = False
                            Dca.pnl[trades["symbol"]] = actual_pnl
                    else:
                        Dca.pnl[trades["symbol"]] = actual_pnl

            # TP reached - sell order (market)
            if sell:
                order = {
                    "symbol": trades["symbol"],
                    "direction": trades["direction"],
                    "side": "sell",
                    "type_sell": "order_sell",
                    "actual_pnl": actual_pnl,
                    "total_cost": trades["total_cost"],
                    "current_price": current_price,
                }
                await self.orders.receive_sell_order(order)

            # Logging configuration
            logging_json = {
                "type": "tp_check",
                "symbol": trades["symbol"],
                "botname": trades["bot"],
                "total_cost": trades["total_cost"],
                "total_amount": trades["total_amount"],
                "current_price": current_price,
                "avg_price": average_buy_price,
                "tp_price": take_profit_price,
                "actual_pnl": actual_pnl,
                "sell": sell,
                "direction": trades["direction"],
            }
            await self.statistic.update_statistic_data(logging_json)

    async def __calculate_dca(self, current_price, trades):
        if trades:
            # Apply price deviation for the first safety order
            next_so_percentage = self.price_deviation
            safety_order_size = self.so
            new_so = False

            # Actual PNL in percent
            actual_pnl = self.utils.calculate_actual_pnl(trades, current_price)

            # Total PNL from base order
            total_pnl = (
                (current_price - trades["bo_price"]) / trades["bo_price"]
            ) * 100

            # Evaluate max deviation and actual deviation from base order
            if self.step_scale == 1:
                # If step scale equals 1
                max_deviation = self.price_deviation * (
                    trades["safetyorders_count"] + 1
                )
                actual_deviation = self.price_deviation * trades["safetyorders_count"]
            else:
                # If step scale is other than 1
                max_deviation = (
                    self.price_deviation
                    * (1 - self.step_scale ** (trades["safetyorders_count"] + 1))
                ) / (1 - self.step_scale)
                max_deviation = round(max_deviation, 2)
                actual_deviation = (
                    self.price_deviation
                    * (1 - self.step_scale ** trades["safetyorders_count"])
                ) / (1 - self.step_scale)

            # Check if safety orders exist yet
            if trades["safetyorders"] and self.max_safety_orders:
                safety_order_size = (
                    trades["safetyorders"][-1]["ordersize"] * self.volume_scale
                )
                next_so_percentage = float(
                    trades["safetyorders"][-1]["so_percentage"]
                ) * float(self.step_scale)
                if len(trades["safetyorders"]) >= 2:
                    next_so_percentage = -abs(next_so_percentage) + -abs(
                        float(trades["safetyorders"][-2]["so_percentage"])
                    )
                else:
                    next_so_percentage = -abs(next_so_percentage) + -abs(
                        self.price_deviation
                    )

                last_so_price = float(trades["safetyorders"][-1]["price"])
            else:
                last_so_price = 0

            # We have not reached the max safety orders
            if self.max_safety_orders and (
                trades["safetyorders_count"] < self.max_safety_orders
            ):

                new_so = False

                if self.dynamic_dca:
                    # Trigger new safety order for dynamic dca
                    if actual_pnl <= -abs(next_so_percentage):
                        if self.dynamic_dca and await self.__dynamic_dca_strategy(
                            trades["symbol"]
                        ):
                            # Set next_so_percentage to current percentage
                            next_so_percentage = actual_pnl
                            new_so = True
                else:
                    # Trigger new safety order for static dca
                    if total_pnl <= -abs(max_deviation):
                        # Set next_so_percentage to diffence between max deviation and actual deviation
                        next_so_percentage = max_deviation - actual_deviation
                        next_so_percentage = round(next_so_percentage, 2)
                        new_so = True

                if new_so:
                    order = {
                        "ordersize": safety_order_size,
                        "symbol": trades["symbol"],
                        "direction": trades["direction"],
                        "botname": trades["bot"],
                        "baseorder": False,
                        "safetyorder": True,
                        "order_count": trades["safetyorders_count"] + 1,
                        "ordertype": trades["ordertype"],
                        "so_percentage": next_so_percentage,
                        "side": "buy",
                    }
                    await self.orders.receive_buy_order(order)

                # Logging configuration
                logging_json = {
                    "type": "dca_check",
                    "symbol": trades["symbol"],
                    "botname": trades["bot"],
                    "so_orders": trades["safetyorders_count"],
                    "last_so_price": last_so_price,
                    "new_so_size": safety_order_size,
                    "price_deviation": next_so_percentage,
                    "actual_pnl": actual_pnl,
                    "new_so": new_so,
                }
                # Send new statistics to statistics module
                await self.statistic.update_statistic_data(logging_json)
            else:
                logging.info(
                    f"Max safety orders reached for {trades["symbol"]}. Not opening more."
                )

    async def process_ticker_data(self, ticker):
        # New price action for DCA calculation
        if ticker["type"] == "ticker_price":
            price = ticker["ticker"]["price"]
            trades = await self.trades.get_trades_for_orders(ticker["ticker"]["symbol"])

            # Check Autopilot
            profit = await self.statistic.get_profit()
            trading_settings = await self.autopilot.calculate_trading_settings(
                profit["funds_locked"]
            )
            # Use Autopilots settings
            if trading_settings:
                self.tp = trading_settings["tp"]
                self.sl = trading_settings["sl"]
            # Use base settings
            else:
                self.tp = self.config.get("tp")
                self.sl = self.config.get("sl", 10000)

            # Check DCA
            await self.__calculate_dca(price, trades)

            # Check TP
            await self.__calculate_tp(price, trades)
