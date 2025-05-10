import model
import helper
import asyncio
import socketio
import json
from service.orders import Orders
from service.filter import Filter
from service.data import Data
from socketio.exceptions import TimeoutError

logging = helper.LoggerFactory.get_logger("logs/signals.log", "sym_signals")


class SignalPlugin:
    def __init__(self, watcher_queue):
        config = helper.Config()
        self.utils = helper.Utils()
        self.orders = Orders()
        self.ordersize = config.get("bo")
        self.max_bots = config.get("max_bots")
        self.btc_pulse = config.get("btc_pulse", False)
        self.plugin_settings = json.loads(config.get("plugin_settings"))
        self.filter = Filter()
        self.filter_values = (
            json.loads(config.get("filter", None))
            if config.get("filter", None)
            else None
        )
        self.currency = config.get("currency").upper()
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
        self.topcoin_limit = config.get("topcoin_limit", None)
        self.timeframe = config.get("timeframe", "1m")
        self.exchange_name = config.get("exchange").upper()
        self.volume = (
            json.loads(config.get("volume", None))
            if config.get("volume", None)
            else None
        )
        self.status = True
        self.watcher_queue = watcher_queue

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

    def __check_entry_point(self, event):
        # btc pulse check
        btc_pulse = True
        if self.btc_pulse:
            btc_pulse = self.filter.btc_pulse_status("5Min", "10Min")

        if btc_pulse:
            signal_name = event["signal_name"]
            symbol = event["symbol"]
            signal = event["signal"]
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
                if exchange == self.exchange_name:
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
                and signal == "BOT_START"
            ):
                return True

            return False
        else:
            logging.info("BTC-Pulse is in downtrend - not starting new deals!")
            return False

    async def run(self):
        async with socketio.AsyncSimpleClient() as sio:
            while self.status:
                if not sio.connected:
                    try:
                        logging.info("Establish connection to sym signal websocket.")
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
                        logging.error(f"Failed to connect to sym signal websocket: {e}")
                    finally:
                        logging.info(f"Reconnect attempt in 10 seconds")
                        await asyncio.sleep(10)
                        continue
                try:
                    event = await sio.receive(timeout=300)
                    if event[0] == "signal":
                        symbol = f"{event[1]['symbol'].upper()}{self.currency}"

                        if self.__check_entry_point(event[1]):
                            running_trades = (
                                await model.Trades.all()
                                .distinct()
                                .values_list("bot", flat=True)
                            )

                            max_bots = await self.__check_max_bots()
                            current_symbol = f"symsignal_{symbol}"

                            if current_symbol not in running_trades and not max_bots:
                                logging.debug(
                                    f"Running trades: {running_trades}, Max Bots: {max_bots}"
                                )

                                logging.info(f"Triggering new trade for {symbol}")

                                # Backend needs symbol with /
                                symbol_full = self.utils.split_symbol(
                                    symbol, self.currency
                                )

                                # Automatically subscribe to reduce load
                                if self.dynamic_dca:
                                    await Data().add_history_data_for_symbol(
                                        symbol_full
                                    )
                                    await self.watcher_queue.put([symbol_full])

                                order = {
                                    "ordersize": self.ordersize,
                                    "symbol": symbol_full,
                                    "direction": "long",
                                    "botname": f"symsignal_{symbol}",
                                    "baseorder": True,
                                    "safetyorder": False,
                                    "order_count": 0,
                                    "ordertype": "market",
                                    "so_percentage": None,
                                    "side": "buy",
                                }
                                await self.orders.receive_buy_order(order)
                except TimeoutError:
                    logging.error(
                        "Didn't get any event after 5 minutes - SocketIO connection seems to hang. Try to reconnect"
                    )
                    await sio.disconnect()
                    continue

    async def shutdown(self):
        self.status = False
