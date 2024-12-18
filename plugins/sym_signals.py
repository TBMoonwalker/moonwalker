from logger import LoggerFactory
from models import Trades
from filter import Filter
from socketio.exceptions import TimeoutError

import asyncio
import socketio
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
        self.exchange = exchange.upper()
        self.currency = currency.upper()
        if pair_denylist:
            self.pair_denylist = pair_denylist.split(",")
        else:
            self.pair_denylist = None
        if pair_allowlist:
            self.pair_allowlist = pair_allowlist.split(",")
        else:
            self.pair_allowlist = None
        self.dynamic_dca = dynamic_dca
        self.topcoin_limit = topcoin_limit
        self.volume = json.loads(volume)

        # Class Attributes
        SignalPlugin.status = True
        SignalPlugin.logging = LoggerFactory.get_logger(
            "logs/signals.log", "sym_signals", log_level=loglevel
        )
        SignalPlugin.logging.info("Initialized")

    def __get_new_symbol_list(self, running_list, new_symbol):
        # New symbols
        add_symbol = [new_symbol]

        # Running symbols
        running_symbols = [
            f"{symbol.upper()}"
            for botsuffix, symbol in [item.split("_") for item in running_list]
        ]

        # Automatically subscribe/unsubscribe symbols in Moonloader to reduce load
        if self.dynamic_dca:
            subscribed_symbols, unsubscribe_symbols, subscribe_symbols = (
                self.filter.subscribe_new_symbols(running_symbols, add_symbol)
            )

            # # Check if new symbol has been subscribed - in case of error, don't create a deal with it!
            # if new_symbol not in subscribe_symbols:
            #     self.logging.error(
            #         f"New symbol {new_symbol} couldn't be added - not in {subscribed_symbols}"
            #     )
            #     new_symbol = None

            self.logging.debug(f"Subscribed symbols: {subscribed_symbols}")
            self.logging.debug(f"Unsubscribed symbols: {unsubscribe_symbols}")

        self.logging.debug(f"Running symbols: {running_symbols}")
        self.logging.debug(f"New symbols: {new_symbol}")

        return new_symbol

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
        signal_id = event["signal_name_id"]
        sym_rank = event["sym_rank"]
        sym_score = event["sym_score"]
        sym_sense = event["sym_sense"]
        vol_score = event["volatility_score"]
        price_action_score = event["price_action_score"]
        market_cap_rank = event["market_cap_rank"]
        volume_24h = event["volume_24h"]
        volume_range = None
        volume_size = None

        for exchange in volume_24h:
            if exchange == self.exchange:
                if volume_24h[exchange].get(self.currency) != None:
                    # DirtyFix: Some volume data misses "k", "M" or "B"
                    if isinstance(volume_24h[exchange].get(self.currency), float):
                        volume_range = "k"
                        volume_size = volume_24h[exchange][self.currency]
                    else:
                        volume_range = volume_24h[exchange][self.currency][-1]
                        volume_size = float(volume_24h[exchange][self.currency][:-1])
                break

        if (
            signal_id in self.plugin_settings["allowed_signals"]
            and self.filter.is_on_allowed_list(symbol, self.pair_allowlist)
            and self.filter.is_within_topcoin_limit(market_cap_rank, self.topcoin_limit)
            and self.filter.has_enough_volume(volume_range, volume_size, self.volume)
            and not self.filter.is_on_deny_list(symbol, self.pair_denylist)
        ):
            return True

        return False

    async def run(self):
        async with socketio.AsyncSimpleClient() as sio:
            while SignalPlugin.status:
                if not sio.connected:
                    try:
                        self.logging.info(
                            "Establish connection to sym signal websocket."
                        )
                        await sio.connect(
                            self.plugin_settings["api_url"],
                            headers={
                                "api-key": self.plugin_settings["api_key"],
                                "user-agent": f"3CQS Signal Client/{self.plugin_settings['api_version']}",
                            },
                            transports=["websocket", "polling"],
                            socketio_path="/stream/v1/signals",
                        )
                    except Exception as e:
                        self.logging.error(
                            f"Failed to connect to sym signal websocket: {e}"
                        )
                    finally:
                        self.logging.info(f"Reconnect attempt in 10 seconds")
                        await asyncio.sleep(10)
                try:
                    event = await sio.receive(timeout=300)
                    if event[0] == "signal":
                        symbol = f"{event[1]['symbol'].upper()}USDT"

                        if self.__check_entry_point(event[1]):
                            running_trades = (
                                await Trades.all()
                                .distinct()
                                .values_list("bot", flat=True)
                            )

                            # symbol = self.__get_new_symbol_list(running_trades, symbol)
                            self.__get_new_symbol_list(running_trades, symbol)

                            # if symbol:
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
                            # else:
                            #     self.logging.error(
                            #         "Error creating an order with symbol - seems to be an unsuccessful subscription on Moonloader"
                            #     )
                except TimeoutError:
                    self.logging.error(
                        "Didn't get any event after 5 minutes - SocketIO connection seems to hang. Try to reconnect"
                    )
                    await sio.disconnect()

    async def shutdown(self):
        SignalPlugin.status = False
