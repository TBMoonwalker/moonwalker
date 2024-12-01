from logger import LoggerFactory
from models import Trades


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
        Trading.logging.info("Initialized")

    async def __get_trade(self, symbol):
        symbol = (symbol + "/" + self.currency).upper()
        try:
            trades = await Trades.filter(symbol=symbol).values()
            return trades[0]
        except:
            Trading.logging.debug(f"No trade for symbol {symbol}")
            return None

    async def sell(self, symbol):
        trades = await self.__get_trade(symbol)
        if trades:
            Trading.logging.debug(f"Manual sell request for {symbol}")
            order = {
                "symbol": trades["symbol"],
                "direction": trades["direction"],
                "botname": trades["bot"],
                "side": "sell",
                "type_sell": "order_sell",
            }
            await Trading.order.put(order)

            # Exchange takes care about the actual values
            current_price = trades["price"]
            total_cost = trades["ordersize"] + trades["fee"]
            average_buy_price = total_cost / trades["amount"]
            actual_pnl = ((current_price - average_buy_price) / average_buy_price) * 100

            logging_json = {
                "type": "tp_check",
                "symbol": trades["symbol"],
                "botname": trades["bot"],
                "total_cost": total_cost,
                "total_amount": trades["amount"],
                "current_price": current_price,
                "avg_price": average_buy_price,
                "tp_price": current_price,
                "actual_pnl": actual_pnl,
                "sell": True,
                "direction": trades["direction"],
            }

            await Trading.statistic.put(logging_json)
            return logging_json
        return None
