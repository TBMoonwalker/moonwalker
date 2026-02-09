"""DCA strategy handling and order logic."""

import importlib
from datetime import datetime, timedelta
from typing import Any

import helper
from service.autopilot import Autopilot
from service.orders import Orders
from service.statistic import Statistic
from service.trades import Trades

logging = helper.LoggerFactory.get_logger("logs/dca.log", "dca")


class Dca:
    """DCA engine for processing ticker data and managing orders."""

    def __init__(self):

        self.autopilot = Autopilot()
        self.orders = Orders()
        self.statistic = Statistic()
        self.trades = Trades()
        self.utils = helper.Utils()
        self.config = None
        self._strategy_cache: dict[tuple[str, str, str], object] = {}

        # Class attributes
        Dca.pnl = {}

    async def __dynamic_dca_strategy(self, symbol):
        result = False

        if self.config.get("dca_strategy", None):
            dca_strategy_plugin = self.__get_strategy_plugin(
                self.config.get("dca_strategy"),
                self.config.get("dca_strategy_timeframe", "1m"),
                "dca",
            )

            result = await dca_strategy_plugin.run(symbol, "buy")

        return result

    def __tp_strategy(self, symbol):
        result = False

        if self.config.get("tp_strategy", None):
            tp_strategy_plugin = self.__get_strategy_plugin(
                self.config.get("tp_strategy"),
                self.config.get("tp_strategy_timeframe", "1m"),
                "tp",
            )

            token, currency = symbol.split("/")
            symbol = f"{token}{currency}"

            result = tp_strategy_plugin.run(symbol, "sell")

        return result

    def __get_strategy_plugin(self, name: str, timeframe: str, kind: str):
        cache_key = (kind, name, timeframe)
        cached = self._strategy_cache.get(cache_key)
        if cached:
            return cached

        module = importlib.import_module(f"strategies.{name}")
        plugin = module.Strategy(timeframe=timeframe)
        self._strategy_cache[cache_key] = plugin
        return plugin

    async def __calculate_tp(self, current_price, trades):
        trailing_tp = self.config.get("trailing_tp", 0)
        max_safety_orders = self.config.get("mstc", 0)
        sell = False

        # Last sell fee has to be considered
        total_cost = trades["total_cost"] + (trades["total_cost"] * trades["fee"])
        average_buy_price = total_cost / trades["total_amount"]

        # Calculate TP/SL
        take_profit_price = average_buy_price * (1 + (self.tp / 100))
        stop_loss_price = average_buy_price * (1 - (self.sl / 100))

        # Check if TP is reached
        if current_price >= take_profit_price:
            sell = True

        # Check if SL is reached
        if (
            current_price <= stop_loss_price
            and max_safety_orders == trades["safetyorders_count"]
        ):
            sell = True

        # Actual PNL in percent (value for profit calculation)
        actual_pnl = self.utils.calculate_actual_pnl(trades, current_price)

        # TP strategy
        if self.config.get("tp_strategy", None) and sell:
            logging.debug("Check if we should sell ...")
            if self.__tp_strategy(trades["symbol"]):
                sell = True
            else:
                sell = False

        # Trailing TP
        if trailing_tp > 0:
            if sell or trades["symbol"] in Dca.pnl:
                # Initialize new symbols
                if trades["symbol"] not in Dca.pnl:
                    Dca.pnl[trades["symbol"]] = 0.0

                if (
                    actual_pnl != Dca.pnl[trades["symbol"]]
                    and Dca.pnl[trades["symbol"]] != 0.0
                ):
                    diff = actual_pnl - Dca.pnl[trades["symbol"]]

                    logging.debug(
                        f"TTP Check: {trades['symbol']} - Actual PNL: {actual_pnl}, Top-PNL: {Dca.pnl[trades['symbol']]}, PNL Difference: {diff}"
                    )

                    # Sell if trailing deviation is reached or actual PNL is under minimum TP
                    if (diff < 0 and abs(diff) > trailing_tp) or (
                        actual_pnl < self.tp and actual_pnl > trailing_tp
                    ):
                        logging.debug(
                            f"TTP Sell: {trades['symbol']} - Percentage decreased - Take profit with difference: {diff}"
                        )
                        sell = True
                        Dca.pnl.pop(trades["symbol"])
                    else:
                        sell = False
                        if actual_pnl > Dca.pnl[trades["symbol"]]:
                            Dca.pnl[trades["symbol"]] = actual_pnl
                else:
                    Dca.pnl[trades["symbol"]] = actual_pnl
                    sell = False

        # Sell if Autopilot is enabled and SL is set
        if self.sl_timeout > 0:
            last_trade_date = datetime.fromtimestamp(
                int(float(trades["timestamp"]) / 1000)
            )
            trade_duration_max_date = datetime.now() - timedelta(days=self.sl_timeout)
            if last_trade_date < trade_duration_max_date and actual_pnl >= -abs(
                self.sl
            ):
                logging.debug(
                    f"Selling {trades['symbol']} because of autopilot settings. "
                )
                sell = True

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
            await self.orders.receive_sell_order(order, self.config)

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
        dynamic_dca = self.config.get("dynamic_dca", False)
        volume_scale = self.config.get("os", 0)
        step_scale = self.config.get("ss", 0)
        max_safety_orders = self.config.get("mstc", 0)
        price_deviation = self.config.get("sos")
        # Apply price deviation for the first safety order
        next_so_percentage = price_deviation
        safety_order_size = self.config.get("so", None)
        new_so = False
        placed_new_so = False

        # Actual PNL in percent
        actual_pnl = self.utils.calculate_actual_pnl(trades, current_price)

        # Total PNL from base order
        total_pnl = ((current_price - trades["bo_price"]) / trades["bo_price"]) * 100

        # Evaluate max deviation and actual deviation from base order
        if step_scale == 1:
            # If step scale equals 1
            max_deviation = price_deviation * (trades["safetyorders_count"] + 1)
            actual_deviation = price_deviation * trades["safetyorders_count"]
        else:
            # If step scale is other than 1
            max_deviation = (
                price_deviation * (1 - step_scale ** (trades["safetyorders_count"] + 1))
            ) / (1 - step_scale)
            max_deviation = round(max_deviation, 2)
            actual_deviation = (
                price_deviation * (1 - step_scale ** trades["safetyorders_count"])
            ) / (1 - step_scale)

        # Check if safety orders exist yet
        if trades["safetyorders"] and max_safety_orders:
            safety_order_size = trades["safetyorders"][-1]["ordersize"] * volume_scale
            next_so_percentage = (
                float(trades["safetyorders"][-1]["so_percentage"]) * step_scale
            )
            if len(trades["safetyorders"]) >= 2:
                next_so_percentage = -abs(next_so_percentage) + -abs(
                    float(trades["safetyorders"][-2]["so_percentage"])
                )
            else:
                next_so_percentage = -abs(next_so_percentage) + -abs(price_deviation)

            last_so_price = float(trades["safetyorders"][-1]["price"])
        else:
            last_so_price = 0

        # We have not reached the max safety orders
        if max_safety_orders and (trades["safetyorders_count"] < max_safety_orders):

            new_so = False

            if dynamic_dca:
                # Trigger new safety order for dynamic dca
                if actual_pnl <= -abs(next_so_percentage):
                    if await self.__dynamic_dca_strategy(trades["symbol"]):
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
                placed_new_so = await self.orders.receive_buy_order(order, self.config)

            # Logging configuration
            logging_json = {
                "type": "dca_check",
                "symbol": trades["symbol"],
                "botname": trades["bot"],
                "so_orders": trades["safetyorders_count"] + int(placed_new_so),
                "last_so_price": last_so_price,
                "new_so_size": safety_order_size,
                "price_deviation": next_so_percentage,
                "actual_pnl": actual_pnl,
                "new_so": placed_new_so,
            }
            # Send new statistics to statistics module
            await self.statistic.update_statistic_data(logging_json)
        else:
            logging.info(
                "Max safety orders reached for %s (configured=%s, current=%s). "
                "Not opening more.",
                trades["symbol"],
                max_safety_orders,
                trades["safetyorders_count"],
            )

    async def process_ticker_data(
        self, ticker: dict[str, Any], config: dict[str, Any]
    ) -> None:
        """Process incoming ticker data and trigger DCA actions."""
        # Get config
        self.config = config

        # New price action for DCA calculation
        if ticker["type"] == "ticker_price":
            price = ticker["ticker"]["price"]
            trades = await self.trades.get_trades_for_orders(ticker["ticker"]["symbol"])
            if trades:

                # Check Autopilot
                profit = await self.statistic.get_profit()
                trading_settings = None

                if profit["funds_locked"]:
                    trading_settings = await self.autopilot.calculate_trading_settings(
                        profit["funds_locked"], self.config
                    )
                # Use Autopilots settings
                if trading_settings:
                    self.tp = trading_settings["tp"]
                    self.sl = trading_settings["sl"]
                    self.sl_timeout = trading_settings["sl_timeout"]
                    self.autopilot_mode = trading_settings["mode"]
                # Use base settings
                else:
                    self.tp = self.config.get("tp", 10000)
                    self.sl = self.config.get("sl", 10000)
                    self.sl_timeout = 0
                    self.autopilot_mode = None

                # Check DCA
                await self.__calculate_dca(price, trades)

                # Check TP
                await self.__calculate_tp(price, trades)
