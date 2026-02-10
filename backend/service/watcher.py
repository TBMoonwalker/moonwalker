"""Exchange watcher and ticker event processing."""

import asyncio
from typing import Any

import ccxt.pro as ccxtpro
import helper
import model
from service.config import Config
from service.dca import Dca
from service.trades import Trades
from tortoise import BaseDBAsyncClient
from tortoise.signals import post_save

logging = helper.LoggerFactory.get_logger("logs/watcher.log", "watcher")
utils = helper.Utils()


class Watcher:
    """Watch exchange tickers and process trading signals."""

    TICKER_PRICE_TYPE = "ticker_price"
    RECONNECT_DELAY = 5
    MAX_RECONNECT_DELAY = 60
    REFRESH_TIMEOUT = 30
    OHLCV_FLUSH_INTERVAL = 1.0
    OHLCV_BATCH_SIZE = 200
    DCA_QUEUE_MAXSIZE = 1000
    OHLCV_QUEUE_MAXSIZE = 5000
    ticker_symbols = []
    candles = {}
    symbol_update_event: asyncio.Event | None = None

    def __init__(self):
        self.trades = Trades()
        self.dca = Dca()
        self.config = None
        self.exchange = None
        self.status = True
        self.symbol_tasks: dict[str, asyncio.Task] = {}
        self.event_queue = asyncio.Queue()
        self.dca_queue = asyncio.Queue(maxsize=self.DCA_QUEUE_MAXSIZE)
        self.ohlcv_queue = asyncio.Queue(maxsize=self.OHLCV_QUEUE_MAXSIZE)
        self.last_price = {}
        self._worker_tasks: list[asyncio.Task] = []

        # Used for cross-task signaling
        Watcher.symbol_update_event = asyncio.Event()
        Watcher.exchange_watcher_ohlcv = True

    async def init(self) -> None:
        """Initialize the watcher from current configuration."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config._cache)

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Reload watcher configuration and exchange client."""
        logging.info("Reload watcher")
        self.config = config
        if config.get("exchange", None):
            self.exchange_class = getattr(ccxtpro, config.get("exchange"))
            self.exchange = self.exchange_class(
                {
                    "apiKey": config.get("key"),
                    "secret": config.get("secret"),
                    "options": {"defaultType": config.get("market", "spot")},
                }
            )
            if config.get("dry_run", True):
                try:
                    self.exchange.enableDemoTrading(True)
                    logging.info(
                        "Enabled CCXT Pro demo trading for exchange '%s'.",
                        config.get("exchange"),
                    )
                except Exception as exc:
                    raise ValueError(
                        "Dry run requires CCXT Pro enableDemoTrading support, but "
                        f"'{config.get('exchange')}' could not enable demo trading."
                    ) from exc
            self.exchange.set_sandbox_mode(config.get("sandbox", False))

        Watcher.exchange_watcher_ohlcv = config.get("watcher_ohlcv", True)

    # ------------------------------------------------------------------- #
    #                Queue-based symbol updates from app.py               #
    # ------------------------------------------------------------------- #

    async def watch_incoming_symbols(self, watcher_queue: asyncio.Queue) -> None:
        """Watch for new symbol lists pushed from the configured signal plugin."""
        logging.info("Started watching incoming symbol updates...")
        while self.status:
            try:
                new_symbol_list = await watcher_queue.get()
                trades = await self.trades.get_symbols()
                for s in new_symbol_list:
                    if s not in trades:
                        trades.append(s)
                if Watcher.exchange_watcher_ohlcv:
                    trades = utils.convert_symbols(
                        trades, self.config.get("timeframe", "1m")
                    )
                Watcher.ticker_symbols = trades
                logging.info(f"Updated symbol list via queue: {Watcher.ticker_symbols}")
                if Watcher.symbol_update_event:
                    Watcher.symbol_update_event.set()
                watcher_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Broad catch keeps the watcher queue alive on unexpected errors.
                logging.error(f"Error in watch_incoming_symbols: {e}", exc_info=True)
                await asyncio.sleep(2)

    # ------------------------------------------------------------------- #
    #                    ORM post_save hooks (DB updates)                 #
    # ------------------------------------------------------------------- #

    @post_save(model.Trades)
    async def watch_trade_symbols(
        sender: type[model.Trades],
        instance: model.Trades,
        created: bool,
        using_db: BaseDBAsyncClient | None,
        update_fields: list[str],
    ) -> None:
        if created:
            try:
                new_symbols = await Trades().get_symbols()
                if Watcher.exchange_watcher_ohlcv:
                    new_symbols = utils.convert_symbols(new_symbols)
                Watcher.ticker_symbols = new_symbols
                if Watcher.symbol_update_event:
                    Watcher.symbol_update_event.set()
                logging.debug(f"Added symbols. New list: {Watcher.ticker_symbols}")
            except Exception as e:
                # Broad catch keeps post-save hooks from crashing the process.
                logging.error(f"Error adding trade symbols: {e}", exc_info=True)

    @post_save(model.ClosedTrades)
    async def watch_closedtrade_symbols(
        sender: type[model.ClosedTrades],
        instance: model.ClosedTrades,
        created: bool,
        using_db: BaseDBAsyncClient | None,
        update_fields: list[str],
    ) -> None:
        if created:
            try:
                new_symbols = await Trades().get_symbols()
                if Watcher.exchange_watcher_ohlcv:
                    new_symbols = utils.convert_symbols(new_symbols)
                Watcher.ticker_symbols = new_symbols
                if Watcher.symbol_update_event:
                    Watcher.symbol_update_event.set()
                logging.debug(f"Removed symbols. New list: {Watcher.ticker_symbols}")
            except Exception as e:
                # Broad catch keeps post-save hooks from crashing the process.
                logging.error(f"Error removing trade symbols: {e}", exc_info=True)

    # ------------------------------------------------------------------- #
    #                           Main Watch Loop                           #
    # ------------------------------------------------------------------- #

    async def __wait_for_updates(self) -> None:
        await asyncio.wait_for(
            self.symbol_update_event.wait(), timeout=self.REFRESH_TIMEOUT
        )
        Watcher.symbol_update_event.clear()

    async def __cleanup_tasks(self, consumer_task: asyncio.Task) -> None:
        for task in self.symbol_tasks.values():
            task.cancel()
        await self.exchange.close()
        for task in self._worker_tasks:
            task.cancel()
        await consumer_task
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)

    async def watch_tickers(self) -> None:
        """Main loop that syncs symbol watchers and restarts them if needed."""
        logging.info("Starting Watcher...")

        Watcher.ticker_symbols = await self.trades.get_symbols()
        if Watcher.exchange_watcher_ohlcv:
            Watcher.ticker_symbols = utils.convert_symbols(
                Watcher.ticker_symbols, self.config.get("timeframe", "1m")
            )

        consumer_task = asyncio.create_task(self.process_events())
        self._worker_tasks = [
            asyncio.create_task(self._process_dca_queue()),
            asyncio.create_task(self._process_ohlcv_queue()),
        ]

        while self.status:
            try:
                await self.__sync_symbol_tasks()

                # Wait for event or periodically refresh
                await self.__wait_for_updates()

            except asyncio.TimeoutError:
                # Regular refresh to detect crashed tasks
                await self.__sync_symbol_tasks()
            except Exception as e:
                # Broad catch ensures the watcher loop continues.
                logging.error(f"Error in watch_tickers: {e}", exc_info=True)
                await asyncio.sleep(5)

        await self.__cleanup_tasks(consumer_task)

    @staticmethod
    def __normalize_symbols(symbols: list[Any] | None) -> list[str]:
        """
        Flatten nested symbol lists, filter out invalid entries,
        and always return a valid list of trading pair strings.
        """
        if not symbols:
            return []

        flat = []
        for s in symbols:
            if isinstance(s, list):
                flat.extend(s)
            elif isinstance(s, str):
                flat.append(s)

        # Keep only real trading pairs (strings containing "/")
        valid = [s for s in flat if isinstance(s, str) and "/" in s]

        # Remove duplicates while preserving order
        return list(dict.fromkeys(valid))

    async def __sync_symbol_tasks(self) -> None:
        # Ensure we have watcher tasks for all active symbols.
        current_symbols = set(self.symbol_tasks.keys())

        # Normalize and sanitize ticker symbols
        flat_symbols = self.__normalize_symbols(Watcher.ticker_symbols)
        Watcher.ticker_symbols = flat_symbols  # keep class-level in sync
        desired_symbols = set(flat_symbols)

        # Nothing to do if there are no valid symbols yet
        if not desired_symbols:
            logging.info("No active symbols to watch. Waiting for new trades...")
            # Optional: cancel existing tasks if any remain
            for sym, task in list(self.symbol_tasks.items()):
                task.cancel()
                del self.symbol_tasks[sym]
            await asyncio.sleep(5)
            return

        # Add new watcher tasks
        for sym in desired_symbols - current_symbols:
            logging.info(f"Starting new watcher for {sym}")
            task = asyncio.create_task(self.watch_symbol_with_reconnect(sym))
            self.symbol_tasks[sym] = task

        # Remove watchers for symbols that are no longer active
        for sym in current_symbols - desired_symbols:
            logging.info(f"Stopping watcher for {sym}")
            task = self.symbol_tasks.pop(sym)
            task.cancel()

        # Restart crashed tasks
        for sym, task in list(self.symbol_tasks.items()):
            if task.done() and not task.cancelled():
                logging.warning(f"Watcher for {sym} crashed — restarting...")
                self.symbol_tasks[sym] = asyncio.create_task(
                    self.watch_symbol_with_reconnect(sym)
                )

    # ------------------------------------------------------------------- #
    #                    Symbol watcher with reconnection                 #
    # ------------------------------------------------------------------- #

    async def watch_symbol_with_reconnect(self, symbol: str) -> None:
        """Wrapper that restarts the watcher on connection failures."""
        delay = self.RECONNECT_DELAY
        while self.status:
            try:
                await self.watch_symbol(symbol)
                if not self.status:
                    break
                delay = self.RECONNECT_DELAY
            except asyncio.CancelledError:
                logging.info(f"Watcher cancelled for {symbol}")
                break
            except ccxtpro.NetworkError as e:
                logging.warning(
                    f"{symbol} network error: {e} — reconnecting in {delay}s"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.MAX_RECONNECT_DELAY)
            except ccxtpro.ExchangeError as e:
                logging.warning(
                    f"{symbol} exchange error: {e} — reconnecting in {delay}s"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.MAX_RECONNECT_DELAY)
            except asyncio.TimeoutError as e:
                logging.warning(
                    f"{symbol} timeout error: {e} — reconnecting in {delay}s"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.MAX_RECONNECT_DELAY)
            except Exception as e:
                # Broad catch to keep reconnection loop alive.
                logging.error(
                    f"{symbol} unexpected error: {e} — reconnecting in {delay}s",
                    exc_info=True,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.MAX_RECONNECT_DELAY)

    async def __process_ohlcv_data(self, symbol: str, ohlcv) -> None:
        price = float(ohlcv[-1][4])
        await self.push_event(symbol, price, ohlcv)

    async def __process_trade_data(self, symbol: str, trades) -> None:
        trade = trades[-1]
        price = float(trade["price"])
        ohlcvc = self.exchange.build_ohlcvc([trade], self.config.get("timeframe", "1m"))
        await self.push_event(symbol, price, ohlcvc)

    async def watch_symbol(self, symbol: str) -> None:
        """Actual exchange streaming for one symbol."""
        logging.info(f"Started websocket stream for {symbol}")
        while self.status:
            if self.exchange:
                try:
                    if Watcher.exchange_watcher_ohlcv:
                        ohlcv = await self.exchange.watch_ohlcv(
                            symbol, self.config.get("timeframe", "1m")
                        )
                        await self.__process_ohlcv_data(symbol, ohlcv)
                    else:
                        trades = await self.exchange.watch_trades(symbol)
                        if trades:
                            await self.__process_trade_data(symbol, trades)
                except ccxtpro.NetworkError as e:
                    logging.warning(f"{symbol}: network error {e}, reconnecting...")
                    await asyncio.sleep(5)
                except ccxtpro.ExchangeError as e:
                    logging.warning(f"{symbol}: exchange error {e}, reconnecting...")
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    raise
                except asyncio.TimeoutError as e:
                    logging.warning(f"{symbol}: timeout error {e}, reconnecting...")
                    await asyncio.sleep(5)
                except ValueError as e:
                    logging.error(f"{symbol}: value error {e}")
                    await asyncio.sleep(5)
                except Exception as e:
                    # Broad catch avoids dropping the websocket loop on unknown errors.
                    logging.error(f"Unexpected error for {symbol}: {e}", exc_info=True)
                    await asyncio.sleep(5)
            else:
                logging.error(
                    "No exchange has been configured yet. Please finalize your configuration."
                )
                await asyncio.sleep(5)

    # ------------------------------------------------------------------- #
    #                         Event processing                            #
    # ------------------------------------------------------------------- #

    async def push_event(self, symbol: str, price: float, ohlcv) -> None:
        last = self.last_price.get(symbol)
        if last != price:
            self.last_price[symbol] = price
            await self.event_queue.put(
                {"symbol": symbol, "price": price, "ohlcv": ohlcv}
            )

    async def process_events(self) -> None:
        """Consumer that handles all incoming ticker events."""
        while self.status:
            try:
                event = await self.event_queue.get()
                symbol, price, ohlcv = event["symbol"], event["price"], event["ohlcv"]
                ticker_price = {
                    "type": self.TICKER_PRICE_TYPE,
                    "ticker": {"symbol": symbol, "price": price},
                }
                self._queue_put(self.dca_queue, ticker_price, "dca")
                payload = self.__prepare_ohlcv_write(symbol, ohlcv)
                if payload:
                    self._queue_put(self.ohlcv_queue, payload, "ohlcv")
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Broad catch keeps consumer running despite occasional bad events.
                logging.error(f"Error processing event: {e}", exc_info=True)

    def _queue_put(self, queue: asyncio.Queue, payload: Any, name: str) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logging.warning(f"{name} queue full; dropping event.")

    async def _process_dca_queue(self) -> None:
        while self.status:
            try:
                ticker_price = await self.dca_queue.get()
                await self.dca.process_ticker_data(ticker_price, self.config)
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Broad catch keeps DCA queue alive on unexpected errors.
                logging.error(f"Error processing DCA queue: {e}", exc_info=True)

    async def _process_ohlcv_queue(self) -> None:
        buffer = []
        while self.status:
            try:
                item = await asyncio.wait_for(
                    self.ohlcv_queue.get(), timeout=self.OHLCV_FLUSH_INTERVAL
                )
                buffer.append(item)
                if len(buffer) >= self.OHLCV_BATCH_SIZE:
                    await self._flush_ohlcv_buffer(buffer)
            except asyncio.TimeoutError:
                if buffer:
                    await self._flush_ohlcv_buffer(buffer)
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Broad catch keeps OHLCV writer alive.
                logging.error(f"Error processing OHLCV queue: {e}", exc_info=True)

        if buffer:
            await self._flush_ohlcv_buffer(buffer)

    async def _flush_ohlcv_buffer(self, buffer: list[dict]) -> None:
        if not buffer:
            return
        payloads = list(buffer)
        buffer.clear()
        try:
            await model.Tickers.bulk_create(
                [model.Tickers(**payload) for payload in payloads]
            )
        except Exception as e:
            # Broad catch prevents write failures from crashing the worker.
            logging.error(f"Error writing OHLCV batch: {e}", exc_info=True)

    def __prepare_ohlcv_write(self, symbol: str, ticker) -> dict | None:
        current_candle = ticker[-1]
        timestamp = current_candle[0]

        last = Watcher.candles.get(symbol)
        if not last or last[0] < timestamp:
            if last:
                t, o1, h1, l1, c1, v1 = last[:6]
                payload = {
                    "timestamp": t,
                    "symbol": symbol,
                    "open": o1,
                    "high": h1,
                    "low": l1,
                    "close": c1,
                    "volume": v1,
                }
            else:
                payload = None
            Watcher.candles[symbol] = current_candle
            return payload
        return None

    # ------------------------------------------------------------------- #
    #                              Shutdown                               #
    # ------------------------------------------------------------------- #

    async def shutdown(self) -> None:
        """Stop watchers and close exchange resources."""
        self.status = False
        for task in self.symbol_tasks.values():
            task.cancel()
        for task in self._worker_tasks:
            task.cancel()
        if self.exchange:
            await self.exchange.close()
        logging.info("Watcher shutdown complete.")
