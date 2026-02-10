"""SymSignals plugin implementation."""

import asyncio
import json
from typing import Any

import helper
import model
import socketio
from service.autopilot import Autopilot
from service.data import Data
from service.filter import Filter
from service.orders import Orders
from service.statistic import Statistic
from socketio.exceptions import TimeoutError

logging = helper.LoggerFactory.get_logger("logs/signal.log", "sym_signals")


class SignalPlugin:
    """SymSignals signal plugin for real-time signal ingestion."""

    def __init__(self, watcher_queue: asyncio.Queue):
        self.utils = helper.Utils()
        self.autopilot = Autopilot()
        self.orders = Orders()
        self.statistic = Statistic()
        self.data = Data()
        self.filter = Filter()
        self.config = None
        self.status = True
        self.watcher_queue = watcher_queue

    async def __check_max_bots(self) -> bool:
        """Check if the maximum number of bots has been reached.

        Determines if new trades should be started based on the configured max_bots
        setting and current number of active trades. Also considers autopilot settings
        if funds are locked.

        Returns:
            True if max bots reached or error occurred, False otherwise

        Raises:
            Exception: If database operation fails
        """
        result = False
        try:
            all_bots = await model.Trades.all().distinct().values_list("bot", flat=True)
            profit = await self.statistic.get_profit()
            self.max_bots = self.config.get("max_bots")

            if profit["funds_locked"] and profit["funds_locked"] > 0:
                trading_settings = await self.autopilot.calculate_trading_settings(
                    profit["funds_locked"], self.config
                )
                if trading_settings:
                    self.max_bots = trading_settings["mad"]
                    

            if all_bots and (len(all_bots) >= self.max_bots):
                result = True
        except Exception as e:
            # Broad catch to avoid stopping the signal loop.
            logging.error(
                f"Couldn't get actual list of bots - not starting new deals! Cause: {e}"
            )
            result = True

        return result

    def __check_entry_point(self, event: dict[str, Any]) -> bool:
        """Check if a signal event meets all entry criteria for trading.

        Validates the signal event against various filters including allow/denylist,
        volume, market cap, BTC pulse, and signal type.

        Args:
            event: Signal event dictionary containing signal data

        Returns:
            True if signal passes all entry checks, False otherwise
        """
        currency = self.config.get("currency").upper()
        signal_settings = json.loads(
            json.dumps(eval(self.config.get("signal_settings")))
        )
        pair_denylist = (
            [
                entry.strip().upper().split("/")[0]
                for entry in self.config.get("pair_denylist", None).split(",")
                if entry.strip()
            ]
            if self.config.get("pair_denylist", None)
            else None
        )
        pair_allowlist = (
            self.config.get("pair_allowlist", None).split(",")
            if self.config.get("pair_allowlist", None)
            else None
        )
        volume = (
            json.loads(self.config.get("volume", None))
            if self.config.get("volume", None)
            else None
        )
        # btc pulse check
        btc_pulse = True
        if self.config.get("btc_pulse", False):
            btc_pulse = self.filter.btc_pulse_status("5Min", "10Min")

        if btc_pulse:
            symbol = event["symbol"]
            signal = event["signal"]
            signal_id = event["signal_name_id"]
            market_cap_rank = event["market_cap_rank"]
            volume_24h = event["volume_24h"]
            volume_range = None
            volume_size = None

            for exchange in volume_24h:
                if exchange == self.config.get("exchange").upper():
                    if volume_24h[exchange].get(currency) is not None:
                        # DirtyFix: Some volume data misses "k", "M" or "B"
                        if isinstance(volume_24h[exchange].get(currency), float):
                            volume_range = "k"
                            volume_size = volume_24h[exchange][currency]
                        else:
                            volume_range = volume_24h[exchange][currency][-1]
                            volume_size = float(volume_24h[exchange][currency][:-1])
                    break
            if (
                signal_id in signal_settings["allowed_signals"]
                and self.filter.is_on_allowed_list(symbol, pair_allowlist)
                and self.filter.is_within_topcoin_limit(
                    market_cap_rank, self.config.get("topcoin_limit", None)
                )
                and self.filter.has_enough_volume(volume_range, volume_size, volume)
                and not self.filter.is_on_deny_list(symbol, pair_denylist)
                and signal == "BOT_START"
            ):
                return True

            return False
        else:
            logging.info("BTC-Pulse is in downtrend - not starting new deals!")
            return False

    async def run(self, config: dict[str, Any]) -> None:
        """Main execution loop for the SymSignals plugin.

        Connects to the SymSignals WebSocket, receives signal events, validates them,
        and triggers new trades when conditions are met. Implements reconnection logic
        with exponential backoff.

        Args:
            config: Configuration dictionary containing plugin settings

        Returns:
            None
        """
        self.config = config
        currency = self.config.get("currency").upper()
        signal_settings = json.loads(
            json.dumps(eval(self.config.get("signal_settings")))
        )
        async with socketio.AsyncSimpleClient() as sio:
            while self.status:
                if not sio.connected:
                    connection_success = False
                    try:
                        logging.info("Establish connection to sym signal websocket.")
                        await sio.connect(
                            signal_settings["api_url"],
                            headers={
                                "api-key": signal_settings["api_key"],
                                "user-agent": f"3CQS Signal Client/{signal_settings['api_version']}",
                            },
                            transports=["websocket", "polling"],
                            socketio_path="/stream/v1/signals",
                        )
                        connection_success = True
                    except Exception as e:
                        # Broad catch to keep reconnect loop alive.
                        logging.error(f"Failed to connect to sym signal websocket: {e}")

                    if not connection_success:
                        logging.info("Reconnect attempt in 10 seconds")
                        await asyncio.sleep(10)
                        continue
                try:
                    event = await sio.receive(timeout=300)
                    if event[0] == "signal":
                        symbol = f"{event[1]['symbol'].upper()}{currency}"
                        history_data = self.config.get("history_from_data", 30)
                        max_bots = await self.__check_max_bots()
                        if not max_bots:
                            if self.__check_entry_point(
                                event[1]
                            ) and await self.data.is_token_old_enough(
                                self.config,
                                self.utils.split_symbol(symbol, currency),
                            ):
                                running_trades = (
                                    await model.Trades.all()
                                    .distinct()
                                    .values_list("bot", flat=True)
                                )

                                current_symbol = f"symsignal_{symbol}"

                                if current_symbol not in running_trades:
                                    logging.debug(f"Running trades: {running_trades}")

                                    logging.info(f"Triggering new trade for {symbol}")

                                    # Backend needs symbol with /
                                    symbol_full = self.utils.split_symbol(
                                        symbol, currency
                                    )

                                    # Automatically subscribe to reduce load
                                    if self.config.get("dynamic_dca", False):
                                        success = (
                                            await Data().add_history_data_for_symbol(
                                                symbol_full,
                                                history_data,
                                                self.config,
                                            )
                                        )
                                        if not success:
                                            logging.error(
                                                f"Not trading {symbol} because history add failed. Please check data.log."
                                            )
                                            continue

                                    await self.watcher_queue.put([symbol_full])

                                    order = {
                                        "ordersize": self.config.get("bo"),
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
                                    await self.orders.receive_buy_order(
                                        order, self.config
                                    )
                        else:
                            logging.debug(
                                f"Max Bots: {max_bots}. Max bots reached, waiting for a new slot"
                            )
                except TimeoutError:
                    logging.error(
                        "Didn't get any event after 5 minutes - SocketIO connection seems to hang. Try to reconnect"
                    )
                    await sio.disconnect()
                    continue
                except Exception as e:
                    # Broad catch to keep signal loop alive.
                    logging.error(f"Error receiving signal - reconnecting. Cause: {e}")
                    await asyncio.sleep(10)
                    await sio.disconnect()
                    continue

    async def shutdown(self) -> None:
        """Shutdown the signal plugin.

        Stops the execution loop by setting the status flag to False.

        Returns:
            None
        """
        self.status = False
