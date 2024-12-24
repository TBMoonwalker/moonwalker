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
        self.filter = Filter(
            ws_url=ws_url, loglevel=loglevel, btc_pulse=btc_pulse, currency=currency
        )
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
        self.btc_pulse = btc_pulse

        # Class Attributes
        SignalPlugin.status = True
        SignalPlugin.logging = LoggerFactory.get_logger(
            "logs/signals.log", "sym_signals", log_level=loglevel
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
        result = False

        # btc pulse check
        btc_pulse = True
        if self.btc_pulse:
            btc_pulse = self.filter.btc_pulse_status("5Min", "10Min")

        if btc_pulse:
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
                            volume_size = float(
                                volume_24h[exchange][self.currency][:-1]
                            )
                    break

            if (
                signal_id in self.plugin_settings["allowed_signals"]
                and self.filter.is_on_allowed_list(symbol, self.pair_allowlist)
                and self.filter.is_within_topcoin_limit(
                    market_cap_rank, self.topcoin_limit
                )
                and self.filter.has_enough_volume(
                    volume_range, volume_size, self.volume
                )
                and not self.filter.is_on_deny_list(symbol, self.pair_denylist)
            ):
                return True

            return False
        else:
            SignalPlugin.logging.info(
                "BTC-Pulse is in downtrend - not starting new deals!"
            )
            return False

    async def run(self):
        async with socketio.AsyncSimpleClient() as sio:
            while SignalPlugin.status:
                if not sio.connected:
                    try:
                        SignalPlugin.logging.info(
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
                        SignalPlugin.logging.error(
                            f"Failed to connect to sym signal websocket: {e}"
                        )
                    finally:
                        SignalPlugin.logging.info(f"Reconnect attempt in 10 seconds")
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

                            max_bots = await self.__check_max_bots()
                            current_symbol = f"symsignal_{symbol}"

                            if current_symbol not in running_trades and not max_bots:
                                SignalPlugin.logging.debug(
                                    f"Running trades: {running_trades}, Max Bots: {max_bots}"
                                )

                                SignalPlugin.logging.info(
                                    f"Triggering new trade for {symbol}"
                                )

                                # Automatically subscribe/unsubscribe symbols in Moonloader to reduce load
                                if self.dynamic_dca:
                                    self.filter.subscribe_symbol(symbol)

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
                except TimeoutError:
                    SignalPlugin.logging.error(
                        "Didn't get any event after 5 minutes - SocketIO connection seems to hang. Try to reconnect"
                    )
                    await sio.disconnect()

    async def shutdown(self):
        SignalPlugin.status = False
