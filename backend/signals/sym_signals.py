"""SymSignals plugin implementation."""

import asyncio
from typing import Any

import helper
import model
import socketio
from service.autopilot import Autopilot
from service.config import resolve_history_lookback_days
from service.data import Data
from service.filter import Filter
from service.indicators import Indicators
from service.orders import Orders
from service.signal_runtime import (
    build_common_runtime_settings,
    is_max_bots_reached,
    parse_signal_settings,
    resolve_max_bots_log_interval,
    update_waiting_log_state,
)
from service.statistic import Statistic
from service.strategy_capability import (
    get_configured_strategy_history_lookback_days,
    get_configured_strategy_min_history_candles,
)
from socketio.exceptions import ConnectionError as SocketConnectionError
from socketio.exceptions import DisconnectedError, TimeoutError
from tortoise.exceptions import BaseORMException

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
        self._currency = "USDC"
        self._signal_settings: dict[str, Any] = {}
        self._pair_denylist: list[str] | None = None
        self._pair_allowlist: list[str] | None = None
        self._volume: dict[str, Any] | None = None
        self._strategy_timeframe = "1m"
        self._exchange_name = ""
        self._required_history_days = 0
        self._required_history_candles = 0

    @staticmethod
    def _parse_signal_settings(raw_value: Any) -> dict[str, Any]:
        """Parse signal settings from config string/dict once per run."""
        return parse_signal_settings(raw_value)

    def _prepare_runtime_settings(self) -> None:
        """Cache parsed runtime settings to avoid per-event parsing overhead."""
        runtime = build_common_runtime_settings(self.config)
        self._currency = str(self.config.get("currency", "USDC")).upper()
        self._signal_settings = self._parse_signal_settings(
            self.config.get("signal_settings")
        )
        self._pair_denylist = runtime.pair_denylist
        self._pair_allowlist = runtime.pair_allowlist
        self._volume = runtime.volume
        self._strategy_timeframe = runtime.strategy_timeframe
        self._exchange_name = str(self.config.get("exchange", "")).upper()
        configured_history_days = resolve_history_lookback_days(
            self.config,
            timeframe=self._strategy_timeframe,
        )
        strategy_history_days = get_configured_strategy_history_lookback_days(
            self.config,
            self._strategy_timeframe,
            include_signal_strategy=False,
        )
        self._required_history_days = max(
            configured_history_days,
            strategy_history_days,
        )
        self._required_history_candles = get_configured_strategy_min_history_candles(
            self.config,
            include_signal_strategy=False,
        )

    def __log_max_bots_waiting(self) -> None:
        """Log max-bot saturation with state/interval throttling."""
        (
            self._max_bots_blocked,
            self._max_bots_last_log,
            should_log,
        ) = update_waiting_log_state(
            self._max_bots_blocked,
            self._max_bots_last_log,
            self._max_bots_log_interval_sec,
        )
        if not should_log:
            return

        logging.debug("Max bots reached, waiting for a free slot.")

    async def __has_sufficient_strategy_history(self, symbol: str) -> bool:
        """Return True when local history satisfies configured DCA/TP warmup."""
        if self._required_history_candles <= 0:
            return True

        available_candles = await self.data.get_resampled_history_candle_count(
            symbol,
            self._strategy_timeframe,
            self._required_history_candles,
        )
        if available_candles >= self._required_history_candles:
            return True

        logging.warning(
            "Not watching %s because only %s/%s %s candles are available after "
            "history sync.",
            symbol,
            available_candles,
            self._required_history_candles,
            self._strategy_timeframe,
        )
        return False

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
        try:
            return await is_max_bots_reached(
                self.config, self.statistic, self.autopilot
            )
        except (BaseORMException, RuntimeError, TypeError, ValueError) as e:
            # Broad catch to avoid stopping the signal loop.
            logging.error(
                "Couldn't get actual list of bots - not starting new deals! "
                "Cause: %s",
                e,
            )
            return True

    async def __check_entry_point(self, event: dict[str, Any]) -> bool:
        """Check if a signal event meets all entry criteria for trading.

        Validates the signal event against various filters including allow/denylist,
        volume, market cap, BTC pulse, and signal type.

        Args:
            event: Signal event dictionary containing signal data

        Returns:
            True if signal passes all entry checks, False otherwise
        """
        # btc pulse check
        btc_pulse = True
        if self.config.get("btc_pulse", False):
            btc_pulse = await self.indicators.calculate_btc_pulse(
                self.config.get("currency", "USDC"),
                self._strategy_timeframe,
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
                if exchange == self._exchange_name:
                    if volume_24h[exchange].get(self._currency) is not None:
                        # DirtyFix: Some volume data misses "k", "M" or "B"
                        if isinstance(volume_24h[exchange].get(self._currency), float):
                            volume_range = "k"
                            volume_size = volume_24h[exchange][self._currency]
                        else:
                            volume_range = volume_24h[exchange][self._currency][-1]
                            volume_size = float(
                                volume_24h[exchange][self._currency][:-1]
                            )
                    break
            if (
                signal_id in self._signal_settings["allowed_signals"]
                and self.filter.is_on_allowed_list(symbol, self._pair_allowlist)
                and self.filter.is_within_topcoin_limit(
                    market_cap_rank, self.config.get("topcoin_limit", None)
                )
                and self.filter.has_enough_volume(
                    volume_range, volume_size, self._volume
                )
                and not self.filter.is_on_deny_list(symbol, self._pair_denylist)
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
        self._max_bots_log_interval_sec = resolve_max_bots_log_interval(self.config)
        self._prepare_runtime_settings()
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
                            self._signal_settings["api_url"],
                            headers={
                                "api-key": self._signal_settings["api_key"],
                                "user-agent": (
                                    "3CQS Signal Client/"
                                    f"{self._signal_settings['api_version']}"
                                ),
                            },
                            transports=["websocket", "polling"],
                            socketio_path="/stream/v1/signals",
                        )
                        connection_success = True
                        idle_timeout_count = 0
                        received_events_since_connect = 0
                    except (
                        OSError,
                        RuntimeError,
                        TypeError,
                        ValueError,
                        SocketConnectionError,
                    ) as e:
                        # Broad catch to keep reconnect loop alive.
                        logging.error(
                            "Failed to connect to sym signal websocket: %s",
                            e,
                        )

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
                        await self.__process_valid_signal(
                            event[1],
                            self._currency,
                            self._required_history_days,
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
                except (
                    KeyError,
                    OSError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                    SocketConnectionError,
                ) as e:
                    # Broad catch to keep signal loop alive.
                    logging.error(
                        "Error receiving signal - reconnecting. Cause: %s",
                        e,
                    )
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

        if self.config.get("dynamic_dca", False) or self._required_history_candles > 0:
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
            if not await self.__has_sufficient_strategy_history(symbol_full):
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
