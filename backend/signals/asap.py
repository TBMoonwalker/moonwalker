"""ASAP signal plugin implementation."""

import asyncio
import importlib
import json
import random
import time
from typing import Any, Optional

import helper
import model
import requests
from service.autopilot import Autopilot
from service.config import resolve_history_lookback_days, resolve_timeframe
from service.data import Data
from service.filter import Filter
from service.indicators import Indicators
from service.orders import Orders
from service.statistic import Statistic
from tenacity import retry, wait_fixed

logging = helper.LoggerFactory.get_logger("logs/signal.log", "asap")


class SignalPlugin:
    """ASAP signal plugin for processing trading signals and managing bot operations.

    This plugin handles signal processing, entry point validation, and trade execution
    for the ASAP trading strategy. It integrates with various services like autopilot,
    orders, filters, and indicators to make trading decisions.
    """

    def __init__(self, watcher_queue: asyncio.Queue):
        """Initialize the ASAP SignalPlugin instance.

        Args:
            watcher_queue: Asyncio queue for communicating with the watcher service
        """
        self.utils = helper.Utils()
        self.autopilot = Autopilot()
        self.data = Data(persist_exchange=True)
        self.orders = Orders()
        self.filter = Filter()
        self.indicators = Indicators()
        self.statistic = Statistic()
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
            ValueError: If configuration is invalid
            RuntimeError: If database operation fails
        """
        result = False
        max_bots = self.config.get("max_bots")
        try:
            all_bots = await model.Trades.all().distinct().values_list("bot", flat=True)

            profit = await self.statistic.get_profit()
            if profit["funds_locked"] and profit["funds_locked"] > 0:
                trading_settings = await self.autopilot.calculate_trading_settings(
                    profit["funds_locked"], self.config
                )
                if trading_settings:
                    max_bots = trading_settings["mad"]

            if all_bots and (len(all_bots) >= max_bots):
                result = True
        except ValueError as e:
            logging.error(
                f"Invalid configuration for max bots check - not starting new deals! Cause: {e}"
            )
            result = True
        except RuntimeError as e:
            logging.error(
                f"Database error while checking max bots - not starting new deals! Cause: {e}"
            )
            result = True
        except Exception as e:
            logging.error(
                f"Unexpected error checking max bots - not starting new deals! Cause: {e}"
            )
            result = True

        return result

    async def __fetch_symbol_list_from_url(self, url: str) -> list[str]:
        """Fetch symbol list JSON from a remote URL without blocking the event loop."""

        def _fetch() -> list[str]:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            payload = response.json()
            pairs = payload.get("pairs", [])
            if not isinstance(pairs, list):
                raise ValueError(
                    "Invalid symbol list payload format: expected 'pairs' list"
                )
            return pairs

        return await asyncio.to_thread(_fetch)

    @helper.async_ttl_cache(maxsize=1024, ttl=900)
    async def __get_new_symbol_list(self, running_list: tuple) -> Optional[list[str]]:
        """Get the list of new symbols to trade.

        Retrieves the symbol list from configuration, ensures history data exists
        for each symbol, and pushes them to watcher queue for processing.

        Args:
            running_list: Tuple of currently running trade bots

        Returns:
            List of symbols to trade, or None if no symbol list configured
        """
        # New symbols
        symbol_list = self.config.get("symbol_list", None)
        history_data = resolve_history_lookback_days(
            self.config,
            timeframe=resolve_timeframe(self.config),
        )
        if symbol_list:
            if "http" in symbol_list:
                symbol_list = await self.__fetch_symbol_list_from_url(symbol_list)
            else:
                symbol_list = symbol_list.split(",")

            # Running symbols
            running_symbols = [
                f"{symbol.upper()}"
                for botsuffix, symbol in [item.split("_") for item in running_list]
            ]

            logging.debug(symbol_list)

            # Add history data for indicators
            for symbol in symbol_list:
                if symbol not in running_symbols:
                    if await self.data.count_history_data_for_symbol(symbol) < 1:
                        if not await self.data.add_history_data_for_symbol(
                            symbol, history_data, self.config
                        ):
                            logging.error(
                                f"Not trading {symbol} because history add failed. Please check data.log."
                            )
                            symbol_list.remove(symbol)
            await self.watcher_queue.put(symbol_list)

            logging.debug(f"Running symbols: {running_symbols}")
            logging.debug(f"New symbols: {symbol_list}")
        return symbol_list

    @retry(wait=wait_fixed(3))
    async def __check_entry_point(self, symbol: str) -> bool:
        """Check if a symbol meets all entry criteria for trading.

        Validates symbol against various filters including allow/denylist, volume,
        market cap, RSI, BTC pulse, and strategy-specific entry conditions.

        Args:
            symbol: The trading symbol to check (e.g., "BTC/USDC")

        Returns:
            True if symbol passes all entry checks, False otherwise

        Raises:
            ValueError: If configuration is invalid
            RuntimeError: If data retrieval fails
        """
        # we only need the plain symbol here:
        symbol_only, currency = symbol.split("/")
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
        signal_strategy_plugin = None
        if self.config.get("signal_strategy", None):
            signal_strategy = importlib.import_module(
                f"strategies.{self.config.get('signal_strategy')}"
            )
            signal_strategy_plugin = signal_strategy.Strategy(
                timeframe=strategy_timeframe,
            )

        # allow/denylist check
        if self.filter.is_on_allowed_list(
            symbol_only, pair_allowlist
        ) and self.filter.is_on_deny_list(symbol_only, pair_denylist):
            logging.info(
                f"Symbol {symbol} is not in your allowlist or is set in your denylist. Ignoring it."
            )
            return False

        try:
            # btc pulse check
            if self.config.get("btc_pulse", False):
                if not await self.indicators.calculate_btc_pulse(
                    self.config.get("currency", "USDC"),
                    strategy_timeframe,
                ):
                    logging.debug(
                        f"Not starting trade for {symbol}, because BTC-Pulse indicates downtrend"
                    )
                    return False

            # volume check
            if volume:
                volume_size, volume_range = self.utils.convert_numbers(
                    await self.indicators.calculate_24h_volume(symbol)
                ).split(" ")

                if not self.filter.has_enough_volume(volume_range, volume_size, volume):
                    logging.info(
                        f"Symbol {symbol} has a 24h volume of {volume_size}{volume_range}, which is under the configured volume of {volume['size']}{volume['range']}"
                    )
                    return False

            # topcoin limit check
            if self.config.get("topcoin_limit", None) and self.config.get(
                "marketcap_cmc_api_key", None
            ):
                marketcap = self.filter.get_cmc_marketcap_rank(
                    self.config.get("marketcap_cmc_api_key", None),
                    symbol_only,
                )
                if marketcap:
                    if not self.filter.is_within_topcoin_limit(
                        marketcap, self.config.get("topcoin_limit", None)
                    ):
                        logging.info(
                            "Symbol %s has a marketcap of %s and is not within your "
                            "topcoin limit of the top %s. Ignoring it.",
                            symbol,
                            marketcap,
                            self.config.get("topcoin_limit", None),
                        )
                        return False

                if self.config.get("rsi_max", None):
                    rsi = await self.indicators.calculate_rsi(
                        symbol, strategy_timeframe, 14
                    )
                    if rsi and rsi > self.config.get("rsi_max", None):
                        logging.info(
                            "Symbol %s has an RSI of %s and exceeds the rsi limit "
                            "of %s. Ignoring it.",
                            symbol,
                            rsi,
                            self.config.get("rsi_max", None),
                        )
                        return False

            # strategy entry check
            if signal_strategy_plugin:
                try:
                    if not await signal_strategy_plugin.run(symbol, "buy"):
                        return False
                except Exception as e:
                    # Broad catch to keep signal processing resilient.
                    logging.error(f"Error running buy strategy. Cause: {e}")
                    return False

            return True

        except Exception as e:
            logging.debug(
                f"No data yet for {symbol} - you need to enable dynamic dca - error: {e}"
            )
            return False

    async def run(self, config: dict[str, Any]) -> None:
        """Main execution loop for the ASAP signal plugin.

        Continuously monitors for new trading opportunities, checks max bots limit,
        validates entry points, and triggers new trades when conditions are met.

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

        while self.status:
            max_bots = await self.__check_max_bots()
            if not max_bots:
                self._max_bots_blocked = False
                running_trades = (
                    await model.Trades.all().distinct().values_list("bot", flat=True)
                )
                symbol_list = await self.__get_new_symbol_list(tuple(running_trades))
                if symbol_list:
                    # Randomize symbols for new deals
                    random.shuffle(symbol_list)
                    for symbol in symbol_list:
                        current_symbol = f"asap_{symbol}"
                        signal = await self.__check_entry_point(symbol)
                        # Check max bots again
                        max_bots = await self.__check_max_bots()
                        if (
                            current_symbol not in running_trades
                            and not max_bots
                            and signal
                        ):
                            logging.info(f"Triggering new trade for {symbol}")
                            order = {
                                "ordersize": self.config.get("bo", 12),
                                "symbol": symbol,
                                "direction": "long",
                                "botname": f"asap_{symbol}",
                                "baseorder": True,
                                "safetyorder": False,
                                "order_count": 0,
                                "ordertype": "market",
                                "so_percentage": None,
                                "side": "buy",
                            }
                            await self.orders.receive_buy_order(order, self.config)
                        # Slow down on many symbols at once
                        await asyncio.sleep(1)
                        if not await self.__check_max_bots():
                            self._max_bots_blocked = False
                else:
                    logging.error(
                        "No symbol list found - please add it with the 'symbol_list' attribute in config.ini."
                    )
            else:
                self.__log_max_bots_waiting()
            await asyncio.sleep(5)

    async def shutdown(self) -> None:
        """Shutdown the signal plugin.

        Stops the execution loop by setting the status flag to False.

        Returns:
            None
        """
        self.status = False
        await self.data.close()
