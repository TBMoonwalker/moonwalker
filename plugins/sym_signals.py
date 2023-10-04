from logger import LoggerFactory
from models import Trades
from filter import Filter
from cachetools import cached, TTLCache
import re
import requests
import socketio


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
        self.exchange = exchange.upper()
        self.currency = currency.upper()

        # Logging
        SignalPlugin.logging = LoggerFactory.get_logger(
            "signals.log", "sym_signals", log_level=loglevel
        )
        SignalPlugin.logging.info("Initialized")

    def __get_new_symbol_list(self, running_list, new_symbol):
        # New symbol
        new_symbol = [new_symbol]

        # Running symbols
        running_symbols = [
            f"{symbol.upper()}"
            for botsuffix, symbol in [item.split("_") for item in running_list]
        ]

        # Existing symbols
        subscribed_symbols = list(map(str.upper, self.__get_symbol_subscription()))

        # Unsubscribe old symbols
        temp_symbols = list(set(subscribed_symbols) - set(running_symbols))
        unsubscribe_symbols = list(set(temp_symbols) - set(new_symbol))
        for symbol in unsubscribe_symbols:
            requests.get(f"{self.ws_url}/streams/remove/{symbol}")

        # Subscribe new symbols
        temp2_symbols = list(set(running_symbols) - set(subscribed_symbols))
        subscribe_symbols = list(set(new_symbol) - set(temp_symbols))
        if temp2_symbols:
            subscribe_symbols = subscribe_symbols + temp2_symbols

        for symbol in subscribe_symbols:
            requests.get(f"{self.ws_url}/streams/add/{symbol}")

        self.logging.debug(f"Subscribed symbols: {subscribed_symbols}")
        self.logging.debug(f"Unsubscribed symbols: {unsubscribe_symbols}")
        self.logging.debug(f"Running symbols: {running_symbols}")
        self.logging.debug(f"New symbols: {new_symbol}")

    def __get_symbol_subscription(self):
        subscribed_list = requests.get(f"{self.ws_url}/status/symbols").json()["result"]
        subscribed_symbols = [
            f"{symbol}"
            for symbol, kline in [item.split("@") for item in subscribed_list]
        ]

        return subscribed_symbols

    async def __check_max_bots(self):
        result = False
        try:
            all_bots = await Trades.all().distinct().values_list("bot", flat=True)
            if all_bots and (len(all_bots) >= self.max_bots):
                result = True
        except:
            result = False

        return result

    def __check_entry_point(self, event):
        result = False

        signal_name = event["signal_name"]
        symbol = event["symbol"]
        signal = event["signal"]
        signal_id = event["signal_name_id"]
        sym_rank = event["sym_rank"]
        sym_score = event["sym_score"]
        sym_sense = event["sym_sense"]
        vol_score = event["volatility_score"]
        price_action_score = event["price_action_score"]
        volume_24h = event["volume_24h"]

        if (
            signal_id in self.plugin_settings["allowed_signals"]
            and symbol != self.currency
        ):
            for exchange in volume_24h:
                if exchange == self.exchange:
                    if volume_24h[exchange].get(self.currency) != None:
                        # DirtyFix: Some volume data misses "k", "M" or "B"
                        if isinstance(volume_24h[exchange].get(self.currency), float):
                            volume_range = "k"
                            volume_size = volume_24h[exchange][self.currency]
                        else:
                            volume_range = volume_24h[exchange][self.currency][-1]
                            volume_size = float(
                                volume_24h[exchange][self.currency][:-1]
                            )
                        if (
                            volume_size >= self.plugin_settings["volume_size"]["size"]
                            and volume_range
                            == self.plugin_settings["volume_size"]["range"]
                            and signal == "BOT_START"
                        ):
                            self.logging.debug(
                                f"{signal} - {signal_name} for symbol {symbol} with volume {volume_size}{volume_range}"
                            )
                            result = True
                            break
                else:
                    result = False

        return result

    async def run(self):
        async with socketio.AsyncSimpleClient() as sio:
            await sio.connect(
                self.plugin_settings["api_url"],
                headers={
                    "api-key": self.plugin_settings["api_key"],
                    "user-agent": f"3CQS Signal Client/{self.plugin_settings['api_version']}",
                },
                transports=["websocket", "polling"],
                socketio_path="/stream/v1/signals",
            )

            while True:
                event = await sio.receive()
                if event[0] == "signal":
                    symbol = f"{event[1]['symbol'].upper()}USDT"

                    if self.__check_entry_point(event[1]):
                        running_trades = (
                            await Trades.all().distinct().values_list("bot", flat=True)
                        )

                        self.__get_new_symbol_list(running_trades, symbol)

                        max_bots = await self.__check_max_bots()
                        current_symbol = f"symsignal_{symbol}"

                        self.logging.debug(
                            f"Running trades: {running_trades}, Max Bots: {max_bots}"
                        )

                        if current_symbol not in running_trades and not max_bots:
                            self.logging.info(f"Triggering new trade for {symbol}")
                            order = {
                                "ordersize": self.ordersize,
                                "symbol": symbol,
                                "direction": "open_long",
                                "botname": f"symsignal_{symbol}",
                                "baseorder": True,
                                "safetyorder": False,
                                "order_count": 0,
                                "ordertype": "market",
                                "so_percentage": None,
                                "side": "buy",
                            }
                            await self.order.put(order)
