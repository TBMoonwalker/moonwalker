from logger import LoggerFactory
from models import Trades
import json
import asyncio


class SignalPlugin:
    def __init__(self, order, token, ordersize, max_bots, loglevel, symbol_list):
        self.order = order
        self.ordersize = ordersize
        self.max_bots = max_bots
        self.symbol_list = list(map(str, symbol_list.split(",")))

        # Logging
        SignalPlugin.logging = LoggerFactory.get_logger(
            "moonwalker.log", "asap", log_level=loglevel
        )
        SignalPlugin.logging.info("Initialized")

    async def __check_max_bots(self):
        result = False
        try:
            all_bots = await Trades.all().distinct().values_list("bot", flat=True)
            if all_bots and (len(all_bots) >= self.max_bots):
                result = True
        except:
            result = False

        return result

    async def run(self):
        while True:
            for symbol in self.symbol_list:
                running_trades = (
                    await Trades.all().distinct().values_list("bot", flat=True)
                )
                max_bots = await self.__check_max_bots()
                if symbol not in running_trades and not max_bots:
                    self.logging.info(f"Triggering new trade for {symbol}")
                    order = {
                        "ordersize": self.ordersize,
                        "symbol": symbol,
                        "direction": "open_long",
                        "botname": f"asap_{symbol}",
                        "baseorder": True,
                        "safetyorder": False,
                        "order_count": 0,
                        "ordertype": "market",
                        "so_percentage": None,
                        "side": "buy",
                    }
                    await self.order.put(order)
            await asyncio.sleep(5)
