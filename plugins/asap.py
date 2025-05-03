import model
import helper
import asyncio
import re
import requests
import json
import random
from service.filter import Filter
from service.orders import Orders
from service.data import Data
from tenacity import retry, wait_fixed
from cachetools import cached, TTLCache

logging = helper.LoggerFactory.get_logger("logs/signals.log", "asap")


class SignalPlugin:
    def __init__(self):
        config = helper.Config()
        self.utils = helper.Utils()
        self.orders = Orders()
        self.ordersize = config.get("bo")
        self.max_bots = config.get("max_bots")
        self.btc_pulse = config.get("btc_pulse", False)
        self.ws_url = config.get("ws_url", None)
        self.plugin_settings = json.loads(config.get("plugin_settings"))
        self.filter = Filter()
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
        self.dynamic_dca = config.get("dynamic_dca", False)
        self.btc_pulse = config.get("btc_pulse", False)
        self.topcoin_limit = config.get("topcoin_limit", None)
        self.timeframe = config.get("timeframe", "1m")
        self.status = True
        logging.info("Initialized")
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
    def __get_new_symbol_list(self, running_list):
        # New symbols
        symbol_list = self.plugin_settings["symbol_list"]
        new_symbol = []
        if "http" in symbol_list:
            symbol_list = requests.get(symbol_list).json()["pairs"]

            new_symbol = [
                f"{symbol}{currency}"
                for symbol, currency in [item.split("/") for item in symbol_list]
            ]
        else:
            new_symbol = list(map(str, symbol_list.split(",")))

        # Running symbols
        running_symbols = [
            f"{symbol.upper()}"
            for botsuffix, symbol in [item.split("_") for item in running_list]
        ]

        logging.debug(f"Running symbols: {running_symbols}")
        logging.debug(f"New symbols: {new_symbol}")
        return new_symbol

    @retry(wait=wait_fixed(3))
    async def __check_entry_point(self, symbol):
        if self.filter_values and self.ws_url:
            try:
                topcoin_limit = True
                marketcap = "N/A"

                # btc pulse check
                btc_pulse = True
                if self.btc_pulse:
                    btc_pulse = self.filter.btc_pulse_status("5Min", "10Min")

                if btc_pulse:
                    # marketcap api needs the symbol without quote
                    mc_symbol = re.split(self.currency, symbol, flags=re.IGNORECASE)[0]

                    if self.topcoin_limit:
                        marketcap = self.filter.get_cmc_marketcap_rank(
                            self.filter_values["marketcap_cmc_api_key"], mc_symbol
                        )

                        topcoin_limit = self.filter.is_within_topcoin_limit(
                            marketcap, self.topcoin_limit
                        )

                    if topcoin_limit:
                        # Automatically subscribe/unsubscribe symbols in Moonloader to reduce load
                        if self.dynamic_dca:

                            await Data().add_history_data_for_symbol(symbol)

                            # TODO - remove after merge
                            self.filter.subscribe_symbol(mc_symbol)

                        rsi_14 = self.filter.get_rsi(
                            symbol, self.timeframe, "14"
                        ).json()
                        ema_slope_30 = self.filter.ema_slope(
                            symbol, self.timeframe, 30
                        ).json()
                        ema_distance = self.filter.ema_distance(
                            symbol, self.timeframe, 30
                        ).json()
                        rsi_limit = self.filter.is_within_rsi_limit(
                            rsi_14["status"], self.filter_values["rsi_max"]
                        )

                        logging.debug(
                            f"Waiting for Entry: SYMBOL: {symbol}, RSI_14: {rsi_14["status"]}, MARKETCAP: {marketcap}, EMA_SLOPE_30: {ema_slope_30["status"]}, EMA_DISTANCE_30: {ema_distance["status"]})"
                        )
                        if (
                            rsi_limit
                            and ema_distance["status"]
                            and self.filter.is_on_allowed_list(
                                symbol, self.pair_allowlist
                            )
                            and not self.filter.is_on_deny_list(
                                symbol, self.pair_denylist
                            )
                        ):
                            return True
                        else:
                            return False
                    else:
                        return False
                else:
                    logging.debug(
                        f"Not starting trade for {symbol}, because BTC-Pulse indicates downtrend"
                    )
                    return False
            except Exception as e:
                logging.debug(
                    f"No data yet for {symbol} - you need to enable dynamic dca - error: {e}"
                )
                return False
        else:
            return True

    async def run(self):
        while self.status:
            running_trades = (
                await model.Trades.all().distinct().values_list("bot", flat=True)
            )
            symbol_list = self.__get_new_symbol_list(tuple(running_trades))
            if symbol_list:
                # Randomize symbols for new deals
                random.shuffle(symbol_list)
                for symbol in symbol_list:
                    max_bots = await self.__check_max_bots()
                    current_symbol = f"asap_{symbol}"
                    signal = await self.__check_entry_point(symbol)
                    if current_symbol not in running_trades and not max_bots and signal:
                        # Backend needs symbol with /
                        symbol_full = self.utils.split_symbol(symbol, self.currency)

                        logging.info(f"Triggering new trade for {symbol}")
                        order = {
                            "ordersize": self.ordersize,
                            "symbol": symbol_full,
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
