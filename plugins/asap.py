from logger import LoggerFactory
from models import Trades
from filter import Filter
from tenacity import retry, wait_fixed
from cachetools import cached, TTLCache
import asyncio
import re
import requests
import json


class SignalPlugin:
    def __init__(
        self,
        order,
        ordersize,
        max_bots,
        ws_url,
        loglevel,
        plugin_settings,
        filter_values,
        exchange,
        currency,
        market,
        pair_denylist,
        pair_allowlist,
        topcoin_limit,
        volume,
        dynamic_dca,
        btc_pulse,
    ):
        self.order = order
        self.ordersize = ordersize
        self.max_bots = max_bots
        self.ws_url = ws_url
        self.plugin_settings = json.loads(plugin_settings)
        self.filter = Filter(ws_url=ws_url, btc_pulse=btc_pulse)
        if filter_values:
            self.filter_values = json.loads(filter_values)
        else:
            self.filter_values = None
        self.currency = currency
        self.dynamic_dca = dynamic_dca
        self.btc_pulse = btc_pulse

        # Class Attributes
        SignalPlugin.status = True
        SignalPlugin.logging = LoggerFactory.get_logger(
            "logs/signals.log", "asap", log_level=loglevel
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

        # Automatically subscribe/unsubscribe symbols in Moonloader to reduce load
        if self.dynamic_dca:
            if running_symbols != new_symbol:
                subscribed_symbols, unsubscribe_symbols = (
                    self.filter.subscribe_new_symbols(running_symbols, new_symbol)
                )

                self.logging.debug(f"Subscribed symbols: {subscribed_symbols}")
                self.logging.debug(f"Unsubscribed symbols: {unsubscribe_symbols}")

        self.logging.debug(f"Running symbols: {running_symbols}")
        self.logging.debug(f"New symbols: {new_symbol}")
        return new_symbol

    @retry(wait=wait_fixed(3))
    def __check_entry_point(self, symbol):
        if self.filter_values and self.ws_url:
            try:
                # btc pulse check
                btc_pulse = True
                if self.btc_pulse:
                    btc_pulse = self.filter.btc_pulse_status("5Min", "10Min")

                if btc_pulse:
                    # marketcap api needs the symbol without quote
                    mc_symbol = re.split(self.currency, symbol, flags=re.IGNORECASE)[0]
                    marketcap = self.filter.get_cmc_marketcap_rank(
                        self.filter_values["marketcap_cmc_api_key"], mc_symbol
                    )
                    topcoin_limit = self.filter.is_within_topcoin_limit(
                        marketcap, self.filter_values["rsi_max"]
                    )
                    if topcoin_limit:
                        rsi = self.filter.get_rsi(symbol, "15Min").json()
                        sma_slope = self.filter.sma_slope(symbol, "15Min").json()
                        ema_cross_15m = self.filter.ema_cross(symbol, "15Min").json()
                        rsi_limit = self.filter.is_within_rsi_limit(
                            rsi["status"], self.filter_values["rsi_max"]
                        )
                        support_level = self.filter.support_level(
                            symbol, "4h", 10
                        ).json()

                        self.logging.debug(
                            f"Waiting for Entry: SYMBOL: {symbol}, RSI: {rsi["status"]}, MARKETCAP: {marketcap}, SMA_SLOPE: {sma_slope["status"]}, EMA_CROSS: {ema_cross_15m["status"]}"
                        )
                        if (
                            rsi_limit
                            and sma_slope["status"] == "upward"
                            and ema_cross_15m["status"] == "up"
                        ) or support_level["status"] == "True":
                            return True
                        else:
                            return False
                    else:
                        return False
                else:
                    self.logging.debug(
                        f"Not starting trade for {symbol}, because BTC is going down"
                    )
                    return False
            except Exception as e:
                self.logging.debug(
                    f"No data yet - you need to enable dynamic dca - error: {e}"
                )
                return False
        else:
            return True

    async def run(self):
        while SignalPlugin.status:
            running_trades = await Trades.all().distinct().values_list("bot", flat=True)
            symbol_list = self.__get_new_symbol_list(tuple(running_trades))
            if symbol_list:
                for symbol in symbol_list:
                    max_bots = await self.__check_max_bots()
                    current_symbol = f"asap_{symbol}"
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
                        await asyncio.sleep(1)
                        self.logging.debug(
                            f"Running trades: {running_trades}, Max Bots: {max_bots}"
                        )

            else:
                self.logging.error(
                    "No symbol list found - please add it with the 'symbol_list' attribute in config.ini."
                )
                break
            await asyncio.sleep(5)

    async def shutdown():
        SignalPlugin.status = False
