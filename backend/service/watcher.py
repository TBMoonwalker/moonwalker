"""Exchange watcher and ticker event processing."""

import asyncio
from typing import Any

import ccxt.pro as ccxtpro
import helper
import model
from service.config import Config, resolve_history_lookback_days, resolve_timeframe
from service.data import Data
from service.database import run_sqlite_write_with_retry
from service.dca import Dca
from service.trades import Trades
from service.watcher_runtime import (
    compose_ticker_symbols,
    get_mandatory_symbols,
    normalize_symbols,
    prepare_ohlcv_write,
)
from service.watcher_tasks import (
    ensure_worker_tasks,
    start_worker_tasks,
    sync_symbol_tasks,
)
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
    BTC_HISTORY_MIN_ROWS = 120
    DCA_WORKER_TASK_NAME = "watcher:dca_worker"
    OHLCV_WORKER_TASK_NAME = "watcher:ohlcv_worker"
    ticker_symbols = []
    candles = {}
    signal_symbols: set[str] = set()
    mandatory_symbols: set[str] = set()
    timeframe = "1m"
    symbol_update_event: asyncio.Event | None = None
    exchange_watcher_ohlcv: bool = True

    def __init__(self) -> None:
        self.trades = Trades()
        self.dca = Dca()
        self.config = None
        self.exchange = None
        self.status = True
        self.symbol_tasks: dict[str, asyncio.Task] = {}
        self.event_queue = asyncio.Queue()
        self.dca_queue: asyncio.Queue[str] = asyncio.Queue(
            maxsize=self.DCA_QUEUE_MAXSIZE
        )
        self.ohlcv_queue = asyncio.Queue(maxsize=self.OHLCV_QUEUE_MAXSIZE)
        self.last_price = {}
        self._pending_dca_payloads: dict[str, dict[str, Any]] = {}
        self._queued_dca_symbols: set[str] = set()
        self._worker_tasks: list[asyncio.Task] = []
        self._reload_lock = asyncio.Lock()
        self._reload_task: asyncio.Task | None = None
        self._pending_reload_config: dict[str, Any] | None = None
        self._btc_warmup_task: asyncio.Task | None = None
        self._btc_warmup_key: tuple[Any, ...] | None = None

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
        self._pending_reload_config = dict(config)
        if self._reload_task is None or self._reload_task.done():
            self._reload_task = asyncio.create_task(self._drain_exchange_reloads())

        Watcher.exchange_watcher_ohlcv = config.get("watcher_ohlcv", True)
        Watcher.timeframe = resolve_timeframe(config)
        Watcher.mandatory_symbols = self.__get_mandatory_symbols(config)
        current_symbols = self.__normalize_symbols(Watcher.ticker_symbols)
        Watcher.ticker_symbols = self.__compose_ticker_symbols(current_symbols)
        if Watcher.symbol_update_event:
            Watcher.symbol_update_event.set()
        self._schedule_btc_pulse_history_warmup(config)

    async def _drain_exchange_reloads(self) -> None:
        """Serialize watcher exchange reloads and coalesce rapid config bursts."""
        while self._pending_reload_config is not None:
            config = self._pending_reload_config
            self._pending_reload_config = None

            try:
                await self._reload_exchange_client(config)
            except asyncio.CancelledError:
                raise
            except (
                AttributeError,
                RuntimeError,
                TypeError,
                ValueError,
                ccxtpro.BaseError,
                OSError,
            ) as exc:
                logging.error(
                    "Failed to reload watcher exchange client: %s",
                    exc,
                    exc_info=True,
                )

    @staticmethod
    def __get_mandatory_symbols(config: dict[str, Any]) -> set[str]:
        """Return symbols that must always be watched regardless of plugin queues."""
        return get_mandatory_symbols(config)

    @staticmethod
    def __compose_ticker_symbols(base_symbols: list[str]) -> list[Any]:
        """Merge trades, signal symbols, and mandatory symbols into watch targets."""
        return compose_ticker_symbols(
            utils,
            base_symbols=base_symbols,
            signal_symbols=Watcher.signal_symbols,
            mandatory_symbols=Watcher.mandatory_symbols,
            exchange_watcher_ohlcv=Watcher.exchange_watcher_ohlcv,
            timeframe=Watcher.timeframe,
        )

    async def _reload_exchange_client(self, config: dict[str, Any]) -> None:
        """Close any existing client and recreate it from latest config."""
        async with self._reload_lock:
            old_exchange = self.exchange
            self.exchange = None

            if old_exchange:
                try:
                    await old_exchange.close()
                except (ccxtpro.BaseError, OSError, RuntimeError) as exc:
                    logging.warning("Error closing previous CCXT Pro client: %s", exc)

            if not config.get("exchange", None):
                return

            options: dict[str, Any] = {"defaultType": config.get("market", "spot")}
            hostname = config.get("exchange_hostname")
            if hostname:
                options["hostname"] = str(hostname).strip()

            exchange_class = getattr(ccxtpro, config.get("exchange"))
            new_exchange = exchange_class(
                {
                    "apiKey": config.get("key"),
                    "secret": config.get("secret"),
                    "options": options,
                }
            )
            if hostname:
                logging.info(
                    "Using custom exchange hostname '%s' for watcher exchange '%s'.",
                    options["hostname"],
                    config.get("exchange"),
                )
            if config.get("dry_run", True):
                try:
                    new_exchange.enableDemoTrading(True)
                    logging.info(
                        "Enabled CCXT Pro demo trading for exchange '%s'.",
                        config.get("exchange"),
                    )
                except (AttributeError, NotImplementedError, ccxtpro.BaseError) as exc:
                    raise ValueError(
                        "Dry run requires CCXT Pro enableDemoTrading support, but "
                        f"'{config.get('exchange')}' could not enable demo trading."
                    ) from exc
            new_exchange.set_sandbox_mode(config.get("sandbox", False))
            self.exchange = new_exchange

    def _schedule_btc_pulse_history_warmup(self, config: dict[str, Any]) -> None:
        """Schedule BTC history prefill to stabilize BTC pulse calculations."""
        if not config.get("btc_pulse", False):
            return

        mandatory_symbols = self.__get_mandatory_symbols(config)
        if not mandatory_symbols:
            return
        btc_symbol = next(iter(mandatory_symbols))

        try:
            history_days = resolve_history_lookback_days(
                config, timeframe=Watcher.timeframe
            )
        except (TypeError, ValueError):
            history_days = 90

        warmup_key = (
            btc_symbol,
            history_days,
            config.get("exchange"),
            config.get("market"),
            config.get("exchange_hostname"),
            bool(config.get("dry_run", True)),
        )
        if warmup_key == self._btc_warmup_key and self._btc_warmup_task:
            if not self._btc_warmup_task.done():
                return

        if self._btc_warmup_task and not self._btc_warmup_task.done():
            self._btc_warmup_task.cancel()

        self._btc_warmup_key = warmup_key
        self._btc_warmup_task = asyncio.create_task(
            self._warmup_btc_pulse_history(btc_symbol, history_days)
        )

    async def _warmup_btc_pulse_history(self, symbol: str, history_days: int) -> None:
        """Backfill BTC history once when required for BTC pulse."""
        data = Data()
        try:
            count = await data.count_history_data_for_symbol(symbol)
            history_rows = 0 if count is False else int(count)
            if history_rows >= self.BTC_HISTORY_MIN_ROWS:
                logging.info(
                    "BTC pulse history warmup skipped for %s, %s rows already present.",
                    symbol,
                    history_rows,
                )
                return

            success = await data.add_history_data_for_symbol(
                symbol, history_days, self.config
            )
            if success:
                logging.info(
                    "BTC pulse history warmup completed for %s (%s days).",
                    symbol,
                    history_days,
                )
            else:
                logging.warning("BTC pulse history warmup failed for %s.", symbol)
        except asyncio.CancelledError:
            raise
        except (RuntimeError, TypeError, ValueError) as exc:
            logging.error(
                "BTC pulse history warmup error for %s: %s", symbol, exc, exc_info=True
            )
        finally:
            await data.close()

    async def _await_btc_warmup_if_needed(self) -> None:
        """Await warmup briefly so startup has BTC history before pulse checks."""
        if not self.config.get("btc_pulse", False):
            return
        if not self._btc_warmup_task:
            return
        try:
            await asyncio.wait_for(self._btc_warmup_task, timeout=25)
        except asyncio.TimeoutError:
            logging.warning("BTC pulse warmup timed out; continuing startup.")
        except (RuntimeError, TypeError, ValueError) as exc:
            logging.warning("BTC pulse warmup completed with warning: %s", exc)

    # ------------------------------------------------------------------- #
    #                Queue-based symbol updates from app.py               #
    # ------------------------------------------------------------------- #

    async def watch_incoming_symbols(self, watcher_queue: asyncio.Queue) -> None:
        """Watch for new symbol lists pushed from the configured signal plugin."""
        logging.info("Started watching incoming symbol updates...")
        while self.status:
            try:
                new_symbol_list = await watcher_queue.get()
                Watcher.signal_symbols = set(self.__normalize_symbols(new_symbol_list))
                trade_symbols = await self.trades.get_symbols()
                Watcher.ticker_symbols = self.__compose_ticker_symbols(trade_symbols)
                logging.info(
                    "Updated symbol list via queue: %s", Watcher.ticker_symbols
                )
                if Watcher.symbol_update_event:
                    Watcher.symbol_update_event.set()
                watcher_queue.task_done()
            except asyncio.CancelledError:
                break
            except (RuntimeError, TypeError, ValueError) as e:
                # Broad catch keeps the watcher queue alive on unexpected errors.
                logging.error("Error in watch_incoming_symbols: %s", e, exc_info=True)
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
        """Refresh watched symbols when a new open trade is created."""
        if created:
            try:
                trade_symbols = await Trades().get_symbols()
                Watcher.ticker_symbols = Watcher.__compose_ticker_symbols(trade_symbols)
                if Watcher.symbol_update_event:
                    Watcher.symbol_update_event.set()
                logging.debug("Added symbols. New list: %s", Watcher.ticker_symbols)
            except (RuntimeError, TypeError, ValueError) as e:
                # Broad catch keeps post-save hooks from crashing the process.
                logging.error("Error adding trade symbols: %s", e, exc_info=True)

    @post_save(model.ClosedTrades)
    async def watch_closedtrade_symbols(
        sender: type[model.ClosedTrades],
        instance: model.ClosedTrades,
        created: bool,
        using_db: BaseDBAsyncClient | None,
        update_fields: list[str],
    ) -> None:
        """Refresh watched symbols when a trade is moved to closed trades."""
        if created:
            try:
                trade_symbols = await Trades().get_symbols()
                Watcher.ticker_symbols = Watcher.__compose_ticker_symbols(trade_symbols)
                if Watcher.symbol_update_event:
                    Watcher.symbol_update_event.set()
                logging.debug("Removed symbols. New list: %s", Watcher.ticker_symbols)
            except (RuntimeError, TypeError, ValueError) as e:
                # Broad catch keeps post-save hooks from crashing the process.
                logging.error("Error removing trade symbols: %s", e, exc_info=True)

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

    def _create_worker_task(self, task_name: str) -> asyncio.Task | None:
        if task_name == self.DCA_WORKER_TASK_NAME:
            return asyncio.create_task(
                self._process_dca_queue(), name=self.DCA_WORKER_TASK_NAME
            )
        if task_name == self.OHLCV_WORKER_TASK_NAME:
            return asyncio.create_task(
                self._process_ohlcv_queue(), name=self.OHLCV_WORKER_TASK_NAME
            )
        return None

    def _start_worker_tasks(self) -> None:
        self._worker_tasks = start_worker_tasks(
            [self.DCA_WORKER_TASK_NAME, self.OHLCV_WORKER_TASK_NAME],
            self._create_worker_task,
        )

    def _ensure_worker_tasks(self) -> None:
        ensure_worker_tasks(self._worker_tasks, self._create_worker_task, logging)

    async def watch_tickers(self) -> None:
        """Main loop that syncs symbol watchers and restarts them if needed."""
        logging.info("Starting Watcher...")
        await self._await_btc_warmup_if_needed()

        trade_symbols = await self.trades.get_symbols()
        Watcher.ticker_symbols = self.__compose_ticker_symbols(trade_symbols)

        consumer_task = asyncio.create_task(self.process_events())
        self._start_worker_tasks()

        while self.status:
            try:
                await self.__sync_symbol_tasks()
                self._ensure_worker_tasks()

                # Wait for event or periodically refresh
                await self.__wait_for_updates()

            except asyncio.TimeoutError:
                # Regular refresh to detect crashed tasks
                await self.__sync_symbol_tasks()
                self._ensure_worker_tasks()
            except (RuntimeError, TypeError, ValueError) as e:
                # Broad catch ensures the watcher loop continues.
                logging.error("Error in watch_tickers: %s", e, exc_info=True)
                await asyncio.sleep(5)

        await self.__cleanup_tasks(consumer_task)

    @staticmethod
    def __normalize_symbols(symbols: list[Any] | None) -> list[str]:
        """
        Flatten nested symbol lists, filter out invalid entries,
        and always return a valid list of trading pair strings.
        """
        return normalize_symbols(symbols)

    async def __sync_symbol_tasks(self) -> None:
        # Normalize and sanitize ticker symbols
        flat_symbols = self.__normalize_symbols(Watcher.ticker_symbols)
        Watcher.ticker_symbols = flat_symbols  # keep class-level in sync
        await sync_symbol_tasks(
            self.symbol_tasks,
            set(flat_symbols),
            lambda symbol: asyncio.create_task(
                self.watch_symbol_with_reconnect(symbol)
            ),
            logging,
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
                logging.info("Watcher cancelled for %s", symbol)
                break
            except ccxtpro.NetworkError as e:
                logging.warning(
                    "%s network error: %s — reconnecting in %ss", symbol, e, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.MAX_RECONNECT_DELAY)
            except ccxtpro.ExchangeError as e:
                logging.warning(
                    "%s exchange error: %s — reconnecting in %ss", symbol, e, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.MAX_RECONNECT_DELAY)
            except asyncio.TimeoutError as e:
                logging.warning(
                    "%s timeout error: %s — reconnecting in %ss", symbol, e, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.MAX_RECONNECT_DELAY)
            except (RuntimeError, TypeError, ValueError, OSError) as e:
                # Broad catch to keep reconnection loop alive.
                logging.error(
                    "%s unexpected error: %s — reconnecting in %ss",
                    symbol,
                    e,
                    delay,
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
        ohlcvc = self.exchange.build_ohlcvc([trade], Watcher.timeframe)
        await self.push_event(symbol, price, ohlcvc)

    async def watch_symbol(self, symbol: str) -> None:
        """Actual exchange streaming for one symbol."""
        logging.info("Started websocket stream for %s", symbol)
        while self.status:
            if self.exchange:
                try:
                    if Watcher.exchange_watcher_ohlcv:
                        ohlcv = await self.exchange.watch_ohlcv(
                            symbol, Watcher.timeframe
                        )
                        await self.__process_ohlcv_data(symbol, ohlcv)
                    else:
                        trades = await self.exchange.watch_trades(symbol)
                        if trades:
                            await self.__process_trade_data(symbol, trades)
                except ccxtpro.NetworkError as e:
                    logging.warning("%s: network error %s, reconnecting...", symbol, e)
                    await asyncio.sleep(5)
                except ccxtpro.ExchangeError as e:
                    logging.warning("%s: exchange error %s, reconnecting...", symbol, e)
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    raise
                except asyncio.TimeoutError as e:
                    logging.warning("%s: timeout error %s, reconnecting...", symbol, e)
                    await asyncio.sleep(5)
                except ValueError as e:
                    logging.error("%s: value error %s", symbol, e)
                    await asyncio.sleep(5)
                except (IndexError, KeyError, RuntimeError, TypeError, OSError) as e:
                    # Broad catch avoids dropping the websocket loop on unknown errors.
                    logging.error(
                        "Unexpected error for %s: %s", symbol, e, exc_info=True
                    )
                    await asyncio.sleep(5)
            else:
                logging.error(
                    "No exchange has been configured yet. Please finalize your configuration."
                )
                await asyncio.sleep(5)

    # ------------------------------------------------------------------- #
    #                         Event processing                            #
    # ------------------------------------------------------------------- #

    async def push_event(self, symbol: str, price: float, ohlcv: Any) -> None:
        """Push ticker event when the latest observed price changed."""
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
                self._queue_dca_payload(ticker_price)
                payload = self.__prepare_ohlcv_write(symbol, ohlcv)
                if payload:
                    self._queue_put(self.ohlcv_queue, payload, "ohlcv")
            except asyncio.CancelledError:
                break
            except (KeyError, RuntimeError, TypeError, ValueError) as e:
                # Broad catch keeps consumer running despite occasional bad events.
                logging.error("Error processing event: %s", e, exc_info=True)

    def _queue_dca_payload(self, payload: dict[str, Any]) -> None:
        """Keep at most one queued DCA job per symbol and overwrite stale payloads."""
        ticker = payload.get("ticker")
        symbol = ticker.get("symbol") if isinstance(ticker, dict) else None
        if not isinstance(symbol, str) or not symbol:
            logging.warning("Skipping invalid DCA payload without symbol: %s", payload)
            return

        self._pending_dca_payloads[symbol] = payload
        if symbol in self._queued_dca_symbols:
            return

        try:
            self.dca_queue.put_nowait(symbol)
            self._queued_dca_symbols.add(symbol)
        except asyncio.QueueFull:
            self._pending_dca_payloads.pop(symbol, None)
            worker_summary = ", ".join(
                f"{task.get_name()}={'done' if task.done() else 'alive'}"
                for task in self._worker_tasks
            )
            logging.warning(
                "dca queue full; dropping event for %s. qsize=%s workers=[%s]",
                symbol,
                self.dca_queue.qsize(),
                worker_summary or "none",
            )

    def _queue_put(self, queue: asyncio.Queue, payload: Any, name: str) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            worker_summary = ", ".join(
                f"{task.get_name()}={'done' if task.done() else 'alive'}"
                for task in self._worker_tasks
            )
            logging.warning(
                "%s queue full; dropping event. qsize=%s workers=[%s]",
                name,
                queue.qsize(),
                worker_summary or "none",
            )

    async def _process_dca_queue(self) -> None:
        while self.status:
            symbol = None
            try:
                symbol = await self.dca_queue.get()
                self._queued_dca_symbols.discard(symbol)
                ticker_price = self._pending_dca_payloads.pop(symbol, None)
                if ticker_price is None:
                    continue
                await self.dca.process_ticker_data(ticker_price, self.config)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001 - Keep worker alive on any failure.
                logging.error("Error processing DCA queue: %s", e, exc_info=True)
            finally:
                if symbol is not None:
                    self.dca_queue.task_done()

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
            except (RuntimeError, TypeError, ValueError) as e:
                # Broad catch keeps OHLCV writer alive.
                logging.error("Error processing OHLCV queue: %s", e, exc_info=True)

        if buffer:
            await self._flush_ohlcv_buffer(buffer)

    async def _flush_ohlcv_buffer(self, buffer: list[dict]) -> None:
        if not buffer:
            return
        payloads = list(buffer)
        buffer.clear()
        try:
            rows = [model.Tickers(**payload) for payload in payloads]
            await run_sqlite_write_with_retry(
                lambda: model.Tickers.bulk_create(rows),
                f"bulk write OHLCV batch ({len(rows)} rows)",
            )
        except (RuntimeError, TypeError, ValueError) as e:
            # Broad catch prevents write failures from crashing the worker.
            logging.error("Error writing OHLCV batch: %s", e, exc_info=True)

    def __prepare_ohlcv_write(self, symbol: str, ticker) -> dict | None:
        return prepare_ohlcv_write(Watcher.candles, symbol, ticker)

    # ------------------------------------------------------------------- #
    #                              Shutdown                               #
    # ------------------------------------------------------------------- #

    async def shutdown(self) -> None:
        """Stop watchers and close exchange resources."""
        self.status = False
        self._pending_reload_config = None
        if self._reload_task is not None and not self._reload_task.done():
            await asyncio.gather(self._reload_task, return_exceptions=True)
            self._reload_task = None
        if self._btc_warmup_task and not self._btc_warmup_task.done():
            self._btc_warmup_task.cancel()
        for task in self.symbol_tasks.values():
            task.cancel()
        for task in self._worker_tasks:
            task.cancel()
        if self.exchange:
            await self.exchange.close()
        logging.info("Watcher shutdown complete.")
