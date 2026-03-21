"""Exchange watcher and ticker event processing."""

import asyncio
from typing import Any

import ccxt.pro as ccxtpro
import helper
import model
from service.config import Config, resolve_history_lookback_days
from service.config_views import ExchangeConnectionConfigView, WatcherRuntimeConfigView
from service.data import Data
from service.database import run_sqlite_write_with_retry
from service.dca import Dca
from service.trades import Trades
from service.watcher_runtime import (
    WatcherRuntimeState,
    compose_ticker_symbols,
    get_active_runtime_state,
)
from service.watcher_runtime import (
    get_live_candle_snapshot as get_runtime_live_candle_snapshot,
)
from service.watcher_runtime import (
    get_mandatory_symbols,
    normalize_symbols,
    prepare_ohlcv_write,
    set_active_runtime_state,
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
    _runtime_state: WatcherRuntimeState | None = None

    @classmethod
    def _get_runtime_state(cls) -> WatcherRuntimeState:
        """Return the active watcher runtime state for this process."""
        if cls._runtime_state is None:
            cls._runtime_state = get_active_runtime_state()
        else:
            set_active_runtime_state(cls._runtime_state)
        return cls._runtime_state

    @classmethod
    def get_live_candle_snapshot(cls, symbol: str) -> list[Any] | None:
        """Return the latest in-memory candle snapshot for a symbol."""
        return get_runtime_live_candle_snapshot(symbol)

    @property
    def runtime_state(self) -> WatcherRuntimeState:
        """Return the active runtime state bound to this watcher instance."""
        return self._get_runtime_state()

    def __init__(self) -> None:
        Watcher._runtime_state = WatcherRuntimeState()
        set_active_runtime_state(Watcher._runtime_state)
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
        self._consumer_task: asyncio.Task | None = None
        self._worker_tasks: list[asyncio.Task] = []
        self._reload_lock = asyncio.Lock()
        self._shutdown_lock = asyncio.Lock()
        self._reload_task: asyncio.Task | None = None
        self._pending_reload_config: dict[str, Any] | None = None
        self._btc_warmup_task: asyncio.Task | None = None
        self._btc_warmup_key: tuple[Any, ...] | None = None

    async def init(self) -> None:
        """Initialize the watcher from current configuration."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config.snapshot())

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Reload watcher configuration and exchange client."""
        logging.info("Reload watcher")
        runtime_state = self.runtime_state
        watcher_config = WatcherRuntimeConfigView.from_config(config)
        self.config = config
        self._pending_reload_config = dict(config)
        if self._reload_task is None or self._reload_task.done():
            self._reload_task = asyncio.create_task(self._drain_exchange_reloads())

        runtime_state.exchange_watcher_ohlcv = watcher_config.watcher_ohlcv
        runtime_state.timeframe = watcher_config.timeframe
        runtime_state.mandatory_symbols = self.__get_mandatory_symbols(config)
        self._refresh_symbol_targets_from_current_state()
        self._schedule_btc_pulse_history_warmup(config, watcher_config)

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

    @classmethod
    def _compose_ticker_symbols(cls, base_symbols: list[str]) -> list[Any]:
        """Merge trades, signal symbols, and mandatory symbols into watch targets."""
        runtime_state = cls._get_runtime_state()
        return compose_ticker_symbols(
            utils,
            base_symbols=base_symbols,
            signal_symbols=runtime_state.signal_symbols,
            mandatory_symbols=runtime_state.mandatory_symbols,
            exchange_watcher_ohlcv=runtime_state.exchange_watcher_ohlcv,
            timeframe=runtime_state.timeframe,
        )

    @classmethod
    def _apply_symbol_targets(
        cls,
        base_symbols: list[str],
        *,
        notify: bool = True,
    ) -> list[Any]:
        """Store recomputed watch targets and optionally wake the refresh loop."""
        runtime_state = cls._get_runtime_state()
        runtime_state.ticker_symbols = cls._compose_ticker_symbols(base_symbols)
        if notify:
            runtime_state.notify_symbol_update()
        return list(runtime_state.ticker_symbols)

    async def _refresh_symbol_targets_from_trades(
        self,
        *,
        signal_symbols: list[Any] | None = None,
        notify: bool = True,
    ) -> list[Any]:
        """Refresh watch targets from persisted trades and optional signal symbols."""
        if signal_symbols is not None:
            self.runtime_state.signal_symbols = set(
                self.__normalize_symbols(signal_symbols)
            )
        trade_symbols = await self.trades.get_symbols()
        return self._apply_symbol_targets(trade_symbols, notify=notify)

    @classmethod
    async def _refresh_symbol_targets_for_trade_change(cls) -> list[Any]:
        """Refresh watch targets after trades changed in the database."""
        trade_symbols = await Trades().get_symbols()
        return cls._apply_symbol_targets(trade_symbols)

    def _refresh_symbol_targets_from_current_state(self) -> list[Any]:
        """Recompose current watch targets after config-only runtime changes."""
        current_symbols = self.__normalize_symbols(self.runtime_state.ticker_symbols)
        return self._apply_symbol_targets(current_symbols)

    async def _reload_exchange_client(self, config: dict[str, Any]) -> None:
        """Close any existing client and recreate it from latest config."""
        async with self._reload_lock:
            old_exchange = self.exchange
            self.exchange = None
            exchange_config = ExchangeConnectionConfigView.from_config(config)

            if old_exchange:
                try:
                    await old_exchange.close()
                except (ccxtpro.BaseError, OSError, RuntimeError) as exc:
                    logging.warning("Error closing previous CCXT Pro client: %s", exc)

            if not exchange_config.exchange:
                return

            options: dict[str, Any] = {"defaultType": exchange_config.market}
            hostname = exchange_config.exchange_hostname
            if hostname:
                options["hostname"] = hostname

            exchange_class = getattr(ccxtpro, exchange_config.exchange)
            new_exchange = exchange_class(
                {
                    "apiKey": exchange_config.key,
                    "secret": exchange_config.secret,
                    "options": options,
                }
            )
            if hostname:
                logging.info(
                    "Using custom exchange hostname '%s' for watcher exchange '%s'.",
                    options["hostname"],
                    exchange_config.exchange,
                )
            if exchange_config.dry_run:
                try:
                    new_exchange.enableDemoTrading(True)
                    logging.info(
                        "Enabled CCXT Pro demo trading for exchange '%s'.",
                        exchange_config.exchange,
                    )
                except (AttributeError, NotImplementedError, ccxtpro.BaseError) as exc:
                    raise ValueError(
                        "Dry run requires CCXT Pro enableDemoTrading support, but "
                        f"'{exchange_config.exchange}' could not enable demo trading."
                    ) from exc
            elif exchange_config.sandbox:
                new_exchange.set_sandbox_mode(True)
            self.exchange = new_exchange

    def _schedule_btc_pulse_history_warmup(
        self,
        config: dict[str, Any],
        watcher_config: WatcherRuntimeConfigView | None = None,
    ) -> None:
        """Schedule BTC history prefill to stabilize BTC pulse calculations."""
        watcher_config = watcher_config or WatcherRuntimeConfigView.from_config(config)
        if not watcher_config.btc_pulse_enabled:
            return

        mandatory_symbols = self.__get_mandatory_symbols(config)
        if not mandatory_symbols:
            return
        btc_symbol = next(iter(mandatory_symbols))

        try:
            history_days = resolve_history_lookback_days(
                config, timeframe=self.runtime_state.timeframe
            )
        except (TypeError, ValueError):
            history_days = 90

        warmup_key = (
            btc_symbol,
            history_days,
            watcher_config.exchange_connection.exchange,
            watcher_config.exchange_connection.market,
            watcher_config.exchange_connection.exchange_hostname,
            watcher_config.exchange_connection.dry_run,
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
        if not WatcherRuntimeConfigView.from_config(
            self.config or {}
        ).btc_pulse_enabled:
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
                ticker_symbols = await self._refresh_symbol_targets_from_trades(
                    signal_symbols=new_symbol_list
                )
                logging.info("Updated symbol list via queue: %s", ticker_symbols)
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
                ticker_symbols = (
                    await Watcher._refresh_symbol_targets_for_trade_change()
                )
                logging.debug("Added symbols. New list: %s", ticker_symbols)
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
                ticker_symbols = (
                    await Watcher._refresh_symbol_targets_for_trade_change()
                )
                logging.debug("Removed symbols. New list: %s", ticker_symbols)
            except (RuntimeError, TypeError, ValueError) as e:
                # Broad catch keeps post-save hooks from crashing the process.
                logging.error("Error removing trade symbols: %s", e, exc_info=True)

    # ------------------------------------------------------------------- #
    #                           Main Watch Loop                           #
    # ------------------------------------------------------------------- #

    async def __wait_for_updates(self) -> None:
        runtime_state = self.runtime_state
        await asyncio.wait_for(
            runtime_state.symbol_update_event.wait(), timeout=self.REFRESH_TIMEOUT
        )
        runtime_state.clear_symbol_update()

    async def _cancel_optional_task(self, task: asyncio.Task | None) -> None:
        """Cancel an optional task and wait for it to finish."""
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _cancel_symbol_tasks(self) -> None:
        """Cancel active per-symbol watcher tasks."""
        tasks = list(self.symbol_tasks.values())
        self.symbol_tasks.clear()
        if not tasks:
            return
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _cancel_worker_tasks(self) -> None:
        """Cancel active worker tasks and clear the registry."""
        tasks = list(self._worker_tasks)
        self._worker_tasks = []
        if not tasks:
            return
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _close_exchange(self) -> None:
        """Close the active exchange client once and clear the reference."""
        exchange = self.exchange
        self.exchange = None
        if exchange is None:
            return
        try:
            await exchange.close()
        except (
            AttributeError,
            RuntimeError,
            TypeError,
            ValueError,
            ccxtpro.BaseError,
            OSError,
        ) as exc:
            logging.warning("Error closing watcher exchange client: %s", exc)

    async def _shutdown_runtime_tasks(self) -> None:
        """Idempotently stop internal watcher tasks and close the exchange."""
        async with self._shutdown_lock:
            reload_task = self._reload_task
            self._reload_task = None
            await self._cancel_optional_task(reload_task)

            btc_warmup_task = self._btc_warmup_task
            self._btc_warmup_task = None
            await self._cancel_optional_task(btc_warmup_task)

            consumer_task = self._consumer_task
            self._consumer_task = None
            await self._cancel_optional_task(consumer_task)

            await self._cancel_symbol_tasks()
            await self._cancel_worker_tasks()
            await self._close_exchange()

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

        await self._refresh_symbol_targets_from_trades(notify=False)

        self._consumer_task = asyncio.create_task(
            self.process_events(), name="watcher:event_consumer"
        )
        self._start_worker_tasks()

        try:
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
        finally:
            await asyncio.shield(self._shutdown_runtime_tasks())

    @staticmethod
    def __normalize_symbols(symbols: list[Any] | None) -> list[str]:
        """
        Flatten nested symbol lists, filter out invalid entries,
        and always return a valid list of trading pair strings.
        """
        return normalize_symbols(symbols)

    async def __sync_symbol_tasks(self) -> None:
        # Normalize and sanitize ticker symbols
        runtime_state = self.runtime_state
        flat_symbols = self.__normalize_symbols(runtime_state.ticker_symbols)
        runtime_state.ticker_symbols = flat_symbols
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

    def _next_reconnect_delay(self, delay: int) -> int:
        """Return the next reconnect delay with the configured ceiling."""
        return min(delay * 2, self.MAX_RECONNECT_DELAY)

    async def _wait_for_symbol_retry(
        self,
        symbol: str,
        category: str,
        error: Exception,
        delay: int,
        *,
        log_level: str = "warning",
        exc_info: bool = False,
    ) -> int:
        """Log a stream failure, wait, and return the next reconnect delay."""
        log_method = logging.error if log_level == "error" else logging.warning
        log_method(
            "%s %s: %s — reconnecting in %ss",
            symbol,
            category,
            error,
            delay,
            exc_info=exc_info,
        )
        await asyncio.sleep(delay)
        return self._next_reconnect_delay(delay)

    async def watch_symbol_with_reconnect(self, symbol: str) -> None:
        """Wrapper that restarts the watcher on connection failures."""
        logging.info("Started websocket stream for %s", symbol)
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
                delay = await self._wait_for_symbol_retry(
                    symbol,
                    "network error",
                    e,
                    delay,
                )
            except ccxtpro.ExchangeError as e:
                delay = await self._wait_for_symbol_retry(
                    symbol,
                    "exchange error",
                    e,
                    delay,
                )
            except asyncio.TimeoutError as e:
                delay = await self._wait_for_symbol_retry(
                    symbol,
                    "timeout error",
                    e,
                    delay,
                )
            except (
                IndexError,
                KeyError,
                RuntimeError,
                TypeError,
                ValueError,
                OSError,
            ) as e:
                # Broad catch to keep reconnection loop alive.
                delay = await self._wait_for_symbol_retry(
                    symbol,
                    "unexpected error",
                    e,
                    delay,
                    exc_info=True,
                    log_level="error",
                )

    async def __process_ohlcv_data(self, symbol: str, ohlcv) -> None:
        price = float(ohlcv[-1][4])
        await self.push_event(symbol, price, ohlcv)

    async def __process_trade_data(self, symbol: str, trades, exchange: Any) -> None:
        trade = trades[-1]
        price = float(trade["price"])
        ohlcvc = exchange.build_ohlcvc([trade], self.runtime_state.timeframe)
        await self.push_event(symbol, price, ohlcvc)

    async def watch_symbol(self, symbol: str) -> None:
        """Process exactly one websocket read cycle for a symbol."""
        exchange = self.exchange
        if exchange is None:
            raise RuntimeError(
                "No exchange has been configured yet. Please finalize your configuration."
            )

        if self.runtime_state.exchange_watcher_ohlcv:
            ohlcv = await exchange.watch_ohlcv(symbol, self.runtime_state.timeframe)
            await self.__process_ohlcv_data(symbol, ohlcv)
            return

        trades = await exchange.watch_trades(symbol)
        if trades:
            await self.__process_trade_data(symbol, trades, exchange)

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
            except (RuntimeError, TypeError, ValueError, OSError) as e:
                # Known runtime failures are logged and the worker keeps going.
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
        return prepare_ohlcv_write(self.runtime_state.candles, symbol, ticker)

    # ------------------------------------------------------------------- #
    #                              Shutdown                               #
    # ------------------------------------------------------------------- #

    async def shutdown(self) -> None:
        """Stop watchers and close exchange resources."""
        self.status = False
        self._pending_reload_config = None
        self.runtime_state.notify_symbol_update()
        await self._shutdown_runtime_tasks()
        logging.info("Watcher shutdown complete.")
