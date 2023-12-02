from logger import LoggerFactory
from models import Trades
from filter import Filter

import asyncio
import websockets
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
        self.plugin_settings = json.loads(plugin_settings)
        self.filter = Filter(ws_url=ws_url, btc_pulse=btc_pulse)
        self.exchange = exchange
        self.currency = currency.upper()
        self.market = market
        self.dynamic_dca = dynamic_dca
        if pair_denylist:
            self.pair_denylist = pair_denylist.split(",")
        else:
            self.pair_denylist = None
        if pair_allowlist:
            self.pair_allowlist = pair_allowlist.split(",")
        else:
            self.pair_allowlist = None

        # Logging
        SignalPlugin.logging = LoggerFactory.get_logger(
            "signals.log", "autocrypto", log_level=loglevel
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

    def __check_entry_point(self, event):
        result = True

        if not event["warning_message"]:
            bot = event["bot"]
            if self.plugin_settings["deny_bots"]:
                if bot in self.plugin_settings["deny_bots"]:
                    self.logging.debug(f"Denied bot: {bot}")
                    result = False

            if event["investment_type"] == "SHORT" and self.market == "spot":
                result = False

            if not self.filter.is_on_allowed_list(
                event["coin"], self.pair_allowlist
            ) or self.filter.is_on_deny_list(event["coin"], self.pair_denylist):
                self.logging.debug(f"Denied coin: {event['coin']}")
                result = False

        return result

    async def run(self):
        async for websocket in websockets.connect(
            self.plugin_settings["api_url"], ssl=True
        ):
            try:
                auth = {
                    "action": "sendMessage",
                    "message": self.plugin_settings["api_key"],
                }

                await websocket.send(json.dumps(auth))

                self.logging.info("Established connection to Autocrypto websocket.")

                async for event in websocket:
                    event = json.loads(event)
                    self.logging.debug(event)
                    if type(event) is dict:
                        signal = event["message"]
                        self.logging.debug(signal)
                        if "coins" in signal:
                            direction = signal["investment_type"]
                            for coin in signal["coins"][self.exchange]:
                                symbol = f"{coin.upper()}USDT"
                                signal["coin"] = coin

                                if self.__check_entry_point(signal):
                                    running_trades = (
                                        await Trades.all()
                                        .distinct()
                                        .values_list("bot", flat=True)
                                    )

                                    max_bots = await self.__check_max_bots()
                                    current_symbol = f"autocrypto_{symbol}"

                                    self.logging.debug(
                                        f"Running trades: {running_trades}, Max Bots: {max_bots}"
                                    )

                                    if (
                                        current_symbol not in running_trades
                                        and not max_bots
                                    ):
                                        self.logging.info(
                                            f"Triggering new trade for {symbol}, Direction: {direction}"
                                        )
                                        order = {
                                            "ordersize": self.ordersize,
                                            "symbol": symbol,
                                            "direction": f"open_{direction.lower()}",
                                            "botname": f"autocrypto_{symbol}",
                                            "baseorder": True,
                                            "safetyorder": False,
                                            "order_count": 0,
                                            "ordertype": "market",
                                            "so_percentage": None,
                                            "side": "buy",
                                        }
                                        await self.order.put(order)

            except websockets.ConnectionClosed:
                self.logging.error(
                    f"Closed connection to Autocrypto websocket, trying to reconnect"
                )
                continue
