from logger import LoggerFactory
from models import Trades
from filter import Filter
from tenacity import retry, wait_fixed
from cachetools import cached, TTLCache
import asyncio
import requests


class SignalPlugin:
    def __init__(
        self,
        order,
        token,
        ordersize,
        max_bots,
        ws_url,
        loglevel,
        plugin_settings,
        filter_values,
        exchange,
        currency,
    ):
        self.order = order
        self.ordersize = ordersize
        self.max_bots = max_bots
        self.ws_url = ws_url
        self.plugin_settings = eval(plugin_settings)
        self.filter = Filter(ws_url=ws_url)
        self.filter_values = eval(filter_values)

        # Logging
        SignalPlugin.logging = LoggerFactory.get_logger(
            "signals.log", "asap", log_level=loglevel
        )
        SignalPlugin.logging.info("Initialized")
        self.logging.debug(self.plugin_settings["symbol_list"])

    async def __check_max_bots(self):
        result = False
        try:
            all_bots = await Trades.all().distinct().values_list("bot", flat=True)
            if all_bots and (len(all_bots) >= self.max_bots):
                result = True
        except:
            result = False

        return result

    @cached(cache=TTLCache(maxsize=1024, ttl=900))
    def __get_new_symbol_list(self, running_list):
        # New symbols
        symbol_list = self.plugin_settings["symbol_list"]
        new_list = []
        if "http" in symbol_list:
            symbol_list = requests.get(symbol_list).json()["pairs"]

            new_list = [
                f"{symbol}{currency}"
                for symbol, currency in [item.split("/") for item in symbol_list]
            ]
            self.logging.debug(f"Got new pairlist: {new_list}")

        else:
            new_list = list(map(str, symbol_list.split(",")))

        # Running symbols
        running_symbols = [
            f"{symbol.upper()}"
            for botsuffix, symbol in [item.split("_") for item in running_list]
        ]

        # Existing symbols
        subscribed_symbols = list(map(str.upper, self.__get_symbol_subscription()))

        # Unsubscribe old symbols
        temp_symbols = list(set(subscribed_symbols) - set(running_symbols))
        unsubscribe_symbols = list(set(temp_symbols) - set(new_list))
        for symbol in unsubscribe_symbols:
            requests.get(f"{self.ws_url}/streams/remove/{symbol}")

        # Subscribe new symbols
        temp2_symbols = list(set(running_symbols) - set(subscribed_symbols))
        subscribe_symbols = list(set(new_list) - set(temp_symbols))
        if temp2_symbols:
            subscribe_symbols = subscribe_symbols + temp2_symbols

        for symbol in subscribe_symbols:
            requests.get(f"{self.ws_url}/streams/add/{symbol}")

        self.logging.debug(f"Subscribed symbols: {subscribed_symbols}")
        self.logging.debug(f"Unsubscribed symbols: {unsubscribe_symbols}")
        self.logging.debug(f"Running symbols: {running_symbols}")
        self.logging.debug(f"New symbols: {new_list}")
        return new_list

    def __get_symbol_subscription(self):
        subscribed_list = requests.get(f"{self.ws_url}/status/symbols").json()["result"]
        subscribed_symbols = [
            f"{symbol}"
            for symbol, kline in [item.split("@") for item in subscribed_list]
        ]

        return subscribed_symbols

    @retry(wait=wait_fixed(3))
    def __check_entry_point(self, symbol):
        try:
            rsi_15m = self.filter.rsi(symbol, "15Min").json()
            if rsi_15m["status"] < self.filter_values["rsi"]:
                return True
            else:
                return False
        except Exception as e:
            self.logging.debug("No data yet - subscribe it")
            return False

    async def run(self):
        while True:
            running_trades = await Trades.all().distinct().values_list("bot", flat=True)
            symbol_list = self.__get_new_symbol_list(tuple(running_trades))
            if symbol_list:
                for symbol in symbol_list:
                    max_bots = await self.__check_max_bots()
                    current_symbol = f"asap_{symbol}"
                    self.logging.debug(
                        f"Running trades: {running_trades}, Max Bots: {max_bots}"
                    )
                    if (
                        current_symbol not in running_trades
                        and not max_bots
                        and self.__check_entry_point(symbol)
                    ):
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
            else:
                self.logging.error(
                    "No symbol list found - please add it with the 'symbol_list' attribute in config.ini."
                )
                break
