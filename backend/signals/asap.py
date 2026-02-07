import model
import helper
import asyncio
import requests
import json
import random
import importlib
from typing import Any, Optional, Dict, List, Tuple
from service.autopilot import Autopilot
from service.filter import Filter
from service.indicators import Indicators
from service.orders import Orders
from service.data import Data
from service.statistic import Statistic
from tenacity import retry, wait_fixed
from asyncache import cached
from cachetools import TTLCache

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
        self.orders = Orders()
        self.filter = Filter()
        self.indicators = Indicators()
        self.statistic = Statistic()
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
            ValueError: If configuration is invalid
            RuntimeError: If database operation fails
        """
        result = False
        max_bots = self.config.get("max_bots", 1)
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

    @cached(cache=TTLCache(maxsize=1024, ttl=900))
    async def __get_new_symbol_list(self, running_list: tuple) -> Optional[list[str]]:
        """Get the list of new symbols to trade.

        Retrieves the symbol list from configuration, adds BTC if BTC-Pulse is enabled,
        and ensures history data exists for each symbol. Puts the symbol list into the
        watcher queue for processing.

        Args:
            running_list: Tuple of currently running trade bots

        Returns:
            List of symbols to trade, or None if no symbol list configured
        """
        # New symbols
        symbol_list = self.config.get("symbol_list", None)
        history_data = self.config.get("history_from_data", 30)
        if symbol_list:
            if "http" in symbol_list:
                symbol_list = requests.get(symbol_list).json()["pairs"]
            else:
                symbol_list = symbol_list.split(",")

            # Add BTC to list if BTC-Pulse is activated
            if self.config.get("btc_pulse", False) and "BTC" not in symbol_list:
                symbol_list.append(
                    ("BTC" + "/" + self.config.get("currency", "USDC")).upper()
                )

            # Running symbols
            running_symbols = [
                f"{symbol.upper()}"
                for botsuffix, symbol in [item.split("_") for item in running_list]
            ]

            logging.debug(symbol_list)

            # Add history data for indicators
            for symbol in symbol_list:
                if symbol not in running_symbols:
                    if await Data().count_history_data_for_symbol(symbol) < 1:
                        if not await Data().add_history_data_for_symbol(symbol, history_data, self.config):
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
            self.config.get("pair_denylist", None).split(",")
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
        signal_strategy_plugin = None
        if self.config.get("signal_strategy", None):
            signal_strategy = importlib.import_module(
                f"strategies.{self.config.get('signal_strategy')}"
            )
            signal_strategy_plugin = signal_strategy.Strategy(
                timeframe=self.config.get("signal_strategy_timeframe", "1min"),
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
                    self.config.get("signal_strategy_timeframe", "1min"),
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
                            f"Symbol {symbol} has a marketcap of {marketcap} and is not within your topcoin limit of the top {self.config.get("topcoin_limit", None)}. Ignoring it."
                        )
                        return False

                if self.config.get("rsi_max", None):
                    rsi = await self.indicators.calculate_rsi(
                        symbol, self.config.get("signal_strategy_timeframe", "1min"), 14
                    )
                    if rsi and rsi > self.config.get("rsi_max", None):
                        logging.info(
                            f"Symbol {symbol} has a rsi of {rsi} and is not within your rsi limit of {self.config.get("rsi_max", None)}. Ignoring it."
                        )
                        return False
                    

            # strategy entry check
            if signal_strategy_plugin:
                try:
                    if not await signal_strategy_plugin.run(symbol, "buy"):
                        return False
                except Exception as e:
                    logging.error(f"Error running buy strategy. Cause: {e}")
                    return False
        

            return True

        except Exception as e:
            logging.debug(
                f"No data yet for {symbol} - you need to enable dynamic dca - error: {e}"
            )
            return False

    async def run(self, config: Dict[str, Any]) -> None:
        """Main execution loop for the ASAP signal plugin.

        Continuously monitors for new trading opportunities, checks max bots limit,
        validates entry points, and triggers new trades when conditions are met.

        Args:
            config: Configuration dictionary containing plugin settings

        Returns:
            None
        """
        self.config = config
        while self.status:
            max_bots = await self.__check_max_bots()
            if not max_bots:
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
                                "ordersize": self.config.get("ordersize", 12),
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
                else:
                    logging.error(
                        "No symbol list found - please add it with the 'symbol_list' attribute in config.ini."
                    )
            else:
                logging.debug(
                    f"Max Bots: {max_bots}. Max bots reached, waiting for a new slot"
                )
            await asyncio.sleep(5)

    def shutdown(self) -> None:
        """Shutdown the signal plugin.

        Stops the execution loop by setting the status flag to False.

        Returns:
            None
        """
        self.status = False
