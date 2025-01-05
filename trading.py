from logger import LoggerFactory
from data import Data


class Trading:
    def __init__(
        self,
        statistic,
        loglevel,
        currency,
        order,
    ):
        self.currency = currency

        # Class Attributes
        Trading.statistic = statistic
        Trading.order = order
        Trading.logging = LoggerFactory.get_logger(
            "logs/trading.log", "trading", log_level=loglevel
        )
        self.data = Data(loglevel)
        Trading.logging.info("Initialized")

    async def manual_sell(self, symbol):
        symbol = self.data.split_symbol(symbol.upper(), self.currency)
        trades = await self.data.get_trades(symbol)
        if trades:
            # Exchange takes care about the actual values
            symbol = trades["symbol"]
            bot = trades["bot"]
            direction = trades["direction"]
            current_price = trades["current_price"]
            total_cost = trades["total_cost"] + trades["fee"]
            average_buy_price = total_cost / trades["total_amount"]
            actual_pnl = self.data.calculate_actual_pnl(trades)

            order = {
                "type_sell": "order_sell",
                "symbol": symbol,
                "botname": bot,
                "direction": direction,
                "side": "sell",
                "actual_pnl": actual_pnl,  # actual_pnl is wrong calculated trades table - must be taken from open trades or better after order
                "total_cost": total_cost,
                "current_price": current_price,
            }
            await Trading.order.put(order)
            Trading.logging.debug(f"Manual sell request for {symbol}")

            logging_json = {
                "type": "tp_check",
                "symbol": symbol,
                "botname": bot,
                "total_cost": total_cost,
                "total_amount": trades["total_amount"],
                "current_price": current_price,
                "avg_price": average_buy_price,
                "tp_price": current_price,
                "actual_pnl": actual_pnl,
                "sell": True,
                "direction": direction,
            }

            await Trading.statistic.put(logging_json)
            return logging_json
        return None

    async def manual_buy(self, symbol, ordersize):
        symbol = self.data.split_symbol(symbol.upper(), self.currency)
        trades = await self.data.get_trades(symbol)
        if trades:
            bot = trades["bot"]
            direction = trades["direction"]
            actual_pnl = self.data.calculate_actual_pnl(trades)
            if trades["safetyorders"]:
                safety_order_count = len(trades["safetyorders"])
                last_so_price = float(trades["safetyorders"][-1]["price"])
            else:
                safety_order_count = 0
                last_so_price = 0

            order = {
                "ordersize": ordersize,
                "symbol": symbol,
                "direction": direction,
                "botname": bot,
                "baseorder": False,
                "safetyorder": True,
                "order_count": safety_order_count + 1,
                "ordertype": "market",
                "so_percentage": actual_pnl,
                "side": "buy",
            }
            # Send new safety order request to exchange module
            await Trading.order.put(order)

            # Logging configuration
            logging_json = {
                "type": "dca_check",
                "symbol": symbol,
                "botname": bot,
                "so_orders": safety_order_count,
                "last_so_price": last_so_price,
                "new_so_size": ordersize,
                "price_deviation": actual_pnl,
                "actual_pnl": actual_pnl,
                "new_so": True,
            }
            # Send new DCA statistics to statistics module
            await Trading.statistic.put(logging_json)
            return logging_json
        else:
            Trading.logging.error(
                f"Manual trade is only for new safety orders right now! No trade for {symbol} found."
            )
        return None

    async def manual_stop(self, symbol):
        symbol = self.data.split_symbol(symbol.upper(), self.currency)
        trades = await self.data.get_trades(symbol)
        bot = trades["bot"]
        if trades:
            result = await self.data.stop_trade(symbol, bot)
            if result:
                return {"status": "ok"}
        else:
            Trading.logging.error(f"Cannot stop trade for {symbol} - No trade found.")
