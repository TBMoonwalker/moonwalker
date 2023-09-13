from logger import Logger
from models import Trades
from tortoise.models import Q
import json


class TradingView:
    def __init__(self, order, token, ordersize):
        self.order = order
        self.token = token
        self.ordersize = ordersize

        # Logging
        self.logging = Logger("main")
        self.logging.info("Tradingview module: Initialized")

    def __authenticate(self, signal):
        if signal["email_token"] == self.token:
            return True
        else:
            return False

    async def __process(self, signal):
        bot_name = signal["botname"]
        opentrade_short = await Trades.filter(
            Q(bot=bot_name), Q(direction="short"), join_type="AND"
        ).count()
        opentrade_long = await Trades.filter(
            Q(bot=bot_name), Q(direction="long"), join_type="AND"
        ).count()

        if "action" in signal:
            # Open Short
            if signal["action"] == "open_short" and not (
                opentrade_short or opentrade_long
            ):
                order = {
                    "ordersize": self.ordersize,
                    "symbol": signal["ticker"],
                    "direction": signal["action"],
                    "botname": bot_name,
                    "baseorder": True,
                    "safetyorder": False,
                    "order_count": 0,
                    "ordertype": "market",
                    "so_percentage": None,
                    "side": "buy",
                }
                await self.order.put(order)
            # Close Short
            elif signal["action"] == "close_short" and opentrade_short:
                order = {
                    "symbol": signal["ticker"],
                    "direction": signal["action"],
                    "botname": bot_name,
                    "side": "sell",
                }
                await self.order.put(order)
            # Open Long
            elif signal["action"] == "open_long" and not (
                opentrade_long or opentrade_short
            ):
                order = {
                    "ordersize": self.ordersize,
                    "symbol": signal["ticker"],
                    "direction": signal["action"],
                    "botname": bot_name,
                    "baseorder": True,
                    "safetyorder": False,
                    "order_count": 0,
                    "ordertype": "market",
                    "so_percentage": None,
                    "side": "buy",
                }
                await self.order.put(order)
            # Close Long
            elif signal["action"] == "close_long" and opentrade_long:
                order = {
                    "symbol": signal["ticker"],
                    "direction": signal["action"],
                    "botname": bot_name,
                    "side": "sell",
                }
                await self.order.put(order)
        else:
            self.logging.error(
                "Tradingview module: Wrong signal syntax (no action attribute)!"
            )

        return "ok"

    async def get(self, data):
        try:
            signal = json.loads(data)
        except ValueError as e:
            self.logging.error("JSON Message is garbage: " + e)

        if self.__authenticate(signal):
            self.logging.debug("Tradingview Module: Received signal:" + str(signal))
            return await self.__process(signal)
        else:
            self.logging.error("Failed authentication")
