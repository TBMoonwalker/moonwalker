import model
import helper
import asyncio
import requests
import json
import random
import importlib
from service.filter import Filter
from service.indicators import Indicators
from service.orders import Orders
from service.data import Data
from tenacity import retry, wait_fixed
from asyncache import cached
from cachetools import TTLCache

logging = helper.LoggerFactory.get_logger("logs/signals.log", "asap")


class SignalPlugin:
    def __init__(self, watcher_queue):
        config = helper.Config()
        self.utils = helper.Utils()
        self.orders = Orders()
        self.filter = Filter()
        self.indicators = Indicators()
        self.ordersize = config.get("bo")
        self.max_bots = config.get("max_bots")
        self.btc_pulse = config.get("btc_pulse", False)
        self.plugin_settings = json.loads(config.get("plugin_settings"))
        self.filter_values = json.loads(config.get("filter", None))
        self.currency = config.get("currency")
        self.pair_denylist = (
            config.get("pair_denylist", None).split(",")
            if config.get("pair_denylist", None)
            else None
        )
        self.pair_allowlist = (
            config.get("pair_allowlist", None).split(",")
            if config.get("pair_allowlist", None)
            else None
        )
        # Import configured strategies
        signal_strategy_plugin = None
        if config.get("signal_strategy", None):
            signal_strategy = importlib.import_module(
                f"strategies.{config.get('signal_strategy')}"
            )
            signal_strategy_plugin = signal_strategy.Strategy(
                timeframe=config.get("signal_strategy_timeframe", "1m"),
            )
        self.strategy = signal_strategy_plugin
        self.dynamic_dca = config.get("dynamic_dca", False)
        self.btc_pulse = config.get("btc_pulse", False)
        self.topcoin_limit = config.get("topcoin_limit", None)
        self.timeframe = config.get("timeframe", "1m")
        self.status = True
        self.watcher_queue = watcher_queue
        logging.debug(self.plugin_settings["symbol_list"])

    async def __check_max_bots(self):
        result = False
        try:
            all_bots = await model.Trades.all().distinct().values_list("bot", flat=True)
            if all_bots and (len(all_bots) >= self.max_bots):
                result = True
        except Exception as e:
            logging.error(
                f"Couldn't get actual list of bots - not starting new deals! Cause: {e}"
            )
            result = True

        return result

    @cached(cache=TTLCache(maxsize=1024, ttl=900))
    async def __get_new_symbol_list(self, running_list):
        # New symbols
        symbol_list = self.plugin_settings["symbol_list"]
        if "http" in symbol_list:
            symbol_list = requests.get(symbol_list).json()["pairs"]

        # Add history data for indicators
        for symbol in symbol_list:
            await Data().add_history_data_for_symbol(symbol)
        await self.watcher_queue.put(symbol_list)

        # Running symbols
        running_symbols = [
            f"{symbol.upper()}"
            for botsuffix, symbol in [item.split("_") for item in running_list]
        ]

        logging.debug(f"Running symbols: {running_symbols}")
        logging.debug(f"New symbols: {symbol_list}")
        return symbol_list

    @retry(wait=wait_fixed(3))
    async def __check_entry_point(self, symbol):
        # allow/denylist check
        # we only need the plain symbol here:
        symbol_only, currency = symbol.split("/")
        if not self.filter.is_on_allowed_list(
            symbol_only, self.pair_allowlist
        ) and self.filter.is_on_deny_list(symbol_only, self.pair_denylist):
            logging.info(
                f"{symbol} is not on your allowlist or on your denylist. Ignoring it."
            )
            return False

        if not self.filter_values:
            return True

        try:
            # btc pulse check
            if self.btc_pulse and not self.filter.btc_pulse_status("5Min", "10Min"):
                logging.info(
                    f"Not starting trade for {symbol}, because BTC-Pulse indicates downtrend"
                )
                return False

            # topcoin limit check
            if self.topcoin_limit:
                marketcap = self.filter.get_cmc_marketcap_rank(
                    self.filter_values["marketcap_cmc_api_key"],
                    symbol_only,
                )
                if marketcap:
                    if not self.filter.is_within_topcoin_limit(
                        marketcap, self.topcoin_limit
                    ):
                        logging.info(
                            f"{symbol} is not within your topcoin limit of the top {self.topcoin_limit}. Ignoring it."
                        )
                        return False

            # strategy entry check
            if self.strategy:
                return await self.strategy.run(symbol)

        except Exception as e:
            logging.debug(
                f"No data yet for {symbol} - you need to enable dynamic dca - error: {e}"
            )
            return False

    async def run(self):
        while self.status:
            running_trades = (
                await model.Trades.all().distinct().values_list("bot", flat=True)
            )
            symbol_list = await self.__get_new_symbol_list(tuple(running_trades))
            if symbol_list:
                # Randomize symbols for new deals
                random.shuffle(symbol_list)
                for symbol in symbol_list:
                    max_bots = await self.__check_max_bots()
                    current_symbol = f"asap_{symbol}"
                    signal = await self.__check_entry_point(symbol)
                    if current_symbol not in running_trades and not max_bots and signal:
                        logging.info(f"Triggering new trade for {symbol}")
                        order = {
                            "ordersize": self.ordersize,
                            "symbol": symbol,
                            "direction": "long",
                            "botname": f"asap_{symbol}",
                            "baseorder": True,
                            "safetyorder": False,
                            "order_count": 0,
                            "ordertype": "market",
                            "so_percentage": None,
                            "side": "buy",
                        }
                        await self.orders.receive_buy_order(order)
                        logging.debug(
                            f"Running trades: {running_trades}, Max Bots: {max_bots}"
                        )

            else:
                logging.error(
                    "No symbol list found - please add it with the 'symbol_list' attribute in config.ini."
                )
                break
            await asyncio.sleep(5)

    async def shutdown(self):
        self.status = False
