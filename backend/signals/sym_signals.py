"""SymSignals plugin implementation."""

import asyncio
import json
import time
from typing import Any

import helper
import model
import socketio
from service.autopilot import Autopilot
from service.config import resolve_history_lookback_days, resolve_timeframe
from service.data import Data
from service.filter import Filter
from service.indicators import Indicators
from service.orders import Orders
from service.statistic import Statistic
from socketio.exceptions import DisconnectedError, TimeoutError

logging = helper.LoggerFactory.get_logger("logs/signal.log", "sym_signals")


class SignalPlugin:
    """SymSignals signal plugin for real-time signal ingestion."""

    SOCKET_IDLE_TIMEOUT_SECONDS = 300
    MAX_IDLE_TIMEOUTS_BEFORE_RECONNECT = 6
    RECONNECT_DELAY_SECONDS = 10
    MAX_ERROR_RECONNECT_DELAY_SECONDS = 300

    def __init__(self, watcher_queue: asyncio.Queue):
        self.utils = helper.Utils()
        self.autopilot = Autopilot()
        self.orders = Orders()
        self.statistic = Statistic()
        self.data = Data(persist_exchange=True)
        self.filter = Filter()
        self.indicators = Indicators()
        self.config = None
        self.status = True
        self.watcher_queue = watcher_queue
        self._max_bots_blocked = False
        self._max_bots_last_log = 0.0
        self._max_bots_log_interval_sec = 60.0

    def __log_max_bots_waiting(self) -> None:
        """Log max-bot saturation with state/interval throttling."""
        now = time.monotonic()
        should_log = (not self._max_bots_blocked) or (
            now - self._max_bots_last_log >= self._max_bots_log_interval_sec
        )
        if not should_log:
            return

        logging.debug("Max bots reached, waiting for a free slot.")
        self._max_bots_blocked = True
        self._max_bots_last_log = now

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

    async def __check_entry_point(self, event: dict[str, Any]) -> bool:
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
        strategy_timeframe = resolve_timeframe(self.config)
        # btc pulse check
        btc_pulse = True
        if self.config.get("btc_pulse", False):
            btc_pulse = await self.indicators.calculate_btc_pulse(
                self.config.get("currency", "USDC"),
                strategy_timeframe,
            )

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
        try:
            self._max_bots_log_interval_sec = max(
                1.0, float(self.config.get("max_bots_log_interval_sec", 60))
            )
        except (TypeError, ValueError):
            self._max_bots_log_interval_sec = 60.0
        currency = self.config.get("currency").upper()
        signal_settings = json.loads(
            json.dumps(eval(self.config.get("signal_settings")))
        )
        idle_timeout_count = 0
        received_events_since_connect = 0
        consecutive_error_events = 0
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
                        idle_timeout_count = 0
                        received_events_since_connect = 0
                    except Exception as e:
                        # Broad catch to keep reconnect loop alive.
                        logging.error(f"Failed to connect to sym signal websocket: {e}")

                    if not connection_success:
                        logging.info(
                            "Reconnect attempt in %s seconds",
                            self.RECONNECT_DELAY_SECONDS,
                        )
                        await asyncio.sleep(self.RECONNECT_DELAY_SECONDS)
                        continue
                try:
                    event = await sio.receive(timeout=self.SOCKET_IDLE_TIMEOUT_SECONDS)
                    idle_timeout_count = 0
                    if not event:
                        continue
                    received_events_since_connect += 1

                    if event[0] == "signal":
                        consecutive_error_events = 0
                        max_bots = await self.__check_max_bots()
                        if max_bots:
                            self.__log_max_bots_waiting()
                            continue

                        self._max_bots_blocked = False
                        history_data = resolve_history_lookback_days(
                            self.config,
                            timeframe=resolve_timeframe(self.config),
                        )
                        await self.__process_valid_signal(
                            event[1],
                            currency,
                            history_data,
                        )
                    elif event[0] == "error":
                        error_payload = event[1] if len(event) == 2 else event[1:]
                        consecutive_error_events += 1
                        reconnect_delay = min(
                            self.RECONNECT_DELAY_SECONDS
                            * (2 ** (consecutive_error_events - 1)),
                            self.MAX_ERROR_RECONNECT_DELAY_SECONDS,
                        )
                        logging.warning(
                            "Received websocket event 'error': %s. Reconnecting in "
                            "%s seconds (consecutive_error_events=%s).",
                            error_payload,
                            reconnect_delay,
                            consecutive_error_events,
                        )
                        await sio.disconnect()
                        await asyncio.sleep(reconnect_delay)
                        continue
                    else:
                        consecutive_error_events = 0
                        logging.debug(
                            "Ignoring non-signal websocket event '%s'.",
                            event[0],
                        )
                except TimeoutError:
                    idle_timeout_count += 1
                    if idle_timeout_count >= self.MAX_IDLE_TIMEOUTS_BEFORE_RECONNECT:
                        no_events_notice = (
                            " No websocket events were received since this connection "
                            "was established."
                            if received_events_since_connect == 0
                            else ""
                        )
                        logging.warning(
                            "No websocket events for %s minutes (%s consecutive "
                            "timeouts). Reconnecting to recover from a possible "
                            "stale connection.%s",
                            int(
                                (self.SOCKET_IDLE_TIMEOUT_SECONDS * idle_timeout_count)
                                / 60
                            ),
                            idle_timeout_count,
                            no_events_notice,
                        )
                        await sio.disconnect()
                        idle_timeout_count = 0
                        received_events_since_connect = 0
                    else:
                        logging.debug(
                            "No websocket events for %s seconds (%s/%s idle "
                            "timeouts). Keeping connection open.",
                            self.SOCKET_IDLE_TIMEOUT_SECONDS * idle_timeout_count,
                            idle_timeout_count,
                            self.MAX_IDLE_TIMEOUTS_BEFORE_RECONNECT,
                        )
                    continue
                except DisconnectedError:
                    logging.warning(
                        "Sym signal websocket disconnected. Reconnecting in %s "
                        "seconds.",
                        self.RECONNECT_DELAY_SECONDS,
                    )
                    await asyncio.sleep(self.RECONNECT_DELAY_SECONDS)
                    continue
                except Exception as e:
                    # Broad catch to keep signal loop alive.
                    logging.error(f"Error receiving signal - reconnecting. Cause: {e}")
                    await asyncio.sleep(self.RECONNECT_DELAY_SECONDS)
                    await sio.disconnect()
                    continue

    async def __process_valid_signal(
        self,
        event: dict[str, Any],
        currency: str,
        history_data: int,
    ) -> None:
        """Process a valid websocket signal and trigger trade creation."""
        symbol = f"{event['symbol'].upper()}{currency}"
        symbol_full = self.utils.split_symbol(symbol, currency)

        is_entry_signal = await self.__check_entry_point(event)
        token_old_enough = await self.data.is_token_old_enough(self.config, symbol_full)
        if not (is_entry_signal and token_old_enough):
            return

        running_trades = (
            await model.Trades.all().distinct().values_list("bot", flat=True)
        )
        current_symbol = f"symsignal_{symbol}"
        if current_symbol in running_trades:
            return

        logging.debug("Running trades: %s", running_trades)
        logging.info("Triggering new trade for %s", symbol)

        if self.config.get("dynamic_dca", False):
            success = await self.data.add_history_data_for_symbol(
                symbol_full,
                history_data,
                self.config,
            )
            if not success:
                logging.error(
                    "Not trading %s because history add failed. Please check data.log.",
                    symbol,
                )
                return

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
        await self.orders.receive_buy_order(order, self.config)

    async def shutdown(self) -> None:
        """Shutdown the signal plugin.

        Stops the execution loop by setting the status flag to False.

        Returns:
            None
        """
        self.status = False
        await self.data.close()
