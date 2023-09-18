from logger import LoggerFactory
from models import Trades
from tortoise.models import Q
import json


class SignalPlugin:
    def __init__(self, order, token, ordersize, max_bots, loglevel, symbol_list):
        self.order = order
        self.token = token
        self.ordersize = ordersize
        self.max_bots = max_bots

        # Logging
        SignalPlugin.logging = LoggerFactory.get_logger(
            "moonwalker.log", "tradingview", log_level=loglevel
        )
        SignalPlugin.logging.info("Initialized")

    def __authenticate(self, signal):
        if signal["email_token"] == self.token:
            return True
        else:
            return False

    async def __check_max_bots(self):
        result = False
        try:
            all_bots = await Trades.all().distinct().values_list("bot", flat=True)
            if all_bots and (len(all_bots) >= self.max_bots):
                result = True
        except:
            result = False

        return result

    async def __process(self, signal):
        bot_name = signal["botname"]
        opentrade_short = await Trades.filter(
            Q(bot=bot_name), Q(direction="short"), join_type="AND"
        ).count()
        opentrade_long = await Trades.filter(
            Q(bot=bot_name), Q(direction="long"), join_type="AND"
        ).count()
        max_bots = await self.__check_max_bots()

        # ToDO - Checks for maximum bots reached - no new bots will be started!
        if "action" in signal:
            print(max_bots)
            print(opentrade_short)
            # Open Short
            if signal["action"] == "open_short" and not (
                opentrade_short or opentrade_long or max_bots
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
                opentrade_long or opentrade_short or max_bots
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
                SignalPlugin.logging.error(
                    f"Trade with symbol {signal['ticker']} already running or wrong signal."
                )
        else:
            SignalPlugin.logging.error("Wrong signal syntax (no action attribute)!")

        return "ok"

    async def get(self, data):
        try:
            signal = json.loads(data)
        except ValueError as e:
            SignalPlugin.logging.error(f"JSON Message is garbage: {e}")

        if self.__authenticate(signal):
            SignalPlugin.logging.debug(f"Received signal: {signal}")
            return await self.__process(signal)
        else:
            SignalPlugin.logging.error("Failed authentication")
