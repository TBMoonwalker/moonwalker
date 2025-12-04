import asyncio
import ccxt.pro as ccxtpro
import logging
from tortoise import BaseDBAsyncClient
from tortoise.signals import post_save

import helper
import model
from service.trades import Trades
from service.dca import Dca

logging = helper.LoggerFactory.get_logger("logs/watcher.log", "watcher")
utils = helper.Utils()


class Watcher:
    ticker_symbols = []
    candles = {}
    exchange_watcher_ohlcv = True
    symbol_update_event: asyncio.Event | None = None

    def __init__(self):
        config = helper.Config()

        self.trades = Trades()
        self.dca = Dca()

        self.exchange_id = config.get("exchange")
        self.exchange_class = getattr(ccxtpro, self.exchange_id)
        self.exchange = self.exchange_class(
            {
                "apiKey": config.get("key"),
                "secret": config.get("secret"),
                "options": {"defaultType": config.get("market", "spot")},
            }
        )
        self.exchange.set_sandbox_mode(config.get("sandbox", False))

        self.market = config.get("market", "spot")
        self.timeframe = config.get("timeframe", "1m")
        Watcher.exchange_watcher_ohlcv = config.get("watcher_ohlcv", True)

        self.status = True
        self.symbol_tasks: dict[str, asyncio.Task] = {}
        self.event_queue = asyncio.Queue()
        self.last_price = {}

        # Used for cross-task signaling
        Watcher.symbol_update_event = asyncio.Event()

    # ------------------------------------------------------------------- #
    #                Queue-based symbol updates from app.py               #
    # ------------------------------------------------------------------- #

    async def watch_incoming_symbols(self, watcher_queue: asyncio.Queue):
        """Watch for new symbol lists pushed from the app."""
        logging.info("Started watching incoming symbol updates...")
        while self.status:
            try:
                new_symbol_list = await watcher_queue.get()
                trades = await self.trades.get_symbols()
                for s in new_symbol_list:
                    if s not in trades:
                        trades.append(s)
                if Watcher.exchange_watcher_ohlcv:
                    trades = utils.convert_symbols(trades)
                Watcher.ticker_symbols = trades
                logging.info(f"Updated symbol list via queue: {Watcher.ticker_symbols}")
                if Watcher.symbol_update_event:
                    Watcher.symbol_update_event.set()
                watcher_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Error in watch_incoming_symbols: {e}")
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
                logging.error(f"Error adding trade symbols: {e}")

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
                logging.error(f"Error removing trade symbols: {e}")

    # ------------------------------------------------------------------- #
    #                           Main Watch Loop                           #
    # ------------------------------------------------------------------- #

    async def watch_tickers(self):
        """Main loop that syncs symbol watchers and restarts them if needed."""
        logging.info("Starting Watcher...")

        Watcher.ticker_symbols = await self.trades.get_symbols()
        if Watcher.exchange_watcher_ohlcv:
            Watcher.ticker_symbols = utils.convert_symbols(Watcher.ticker_symbols)

        consumer_task = asyncio.create_task(self.process_events())

        while self.status:
            try:
                await self.sync_symbol_tasks()

                # Wait for event or periodically refresh
                await asyncio.wait_for(Watcher.symbol_update_event.wait(), timeout=30)
                Watcher.symbol_update_event.clear()

            except asyncio.TimeoutError:
                # Regular refresh to detect crashed tasks
                await self.sync_symbol_tasks()
            except Exception as e:
                logging.error(f"Error in watch_tickers: {e}")
                await asyncio.sleep(5)

        for task in self.symbol_tasks.values():
            task.cancel()
        await self.exchange.close()
        await consumer_task

    @staticmethod
    def normalize_symbols(symbols):
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

    async def sync_symbol_tasks(self):
        # Ensure we have watcher tasks for all active symbols.
        current_symbols = set(self.symbol_tasks.keys())

        # Normalize and sanitize ticker symbols
        flat_symbols = self.normalize_symbols(Watcher.ticker_symbols)
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

    async def watch_symbol_with_reconnect(self, symbol: str):
        """Wrapper that restarts the watcher on connection failures."""
        reconnect_delay = 5
        while self.status:
            try:
                await self.watch_symbol(symbol)
            except asyncio.CancelledError:
                logging.info(f"Watcher cancelled for {symbol}")
                break
            except Exception as e:
                logging.warning(
                    f"{symbol} watcher error: {e} — reconnecting in {reconnect_delay}s"
                )
                await asyncio.sleep(reconnect_delay)
                # Exponential backoff up to 60s
                reconnect_delay = min(reconnect_delay * 2, 60)

    async def watch_symbol(self, symbol: str):
        """Actual exchange streaming for one symbol."""
        logging.info(f"Started websocket stream for {symbol}")
        while self.status:
            try:
                if Watcher.exchange_watcher_ohlcv:
                    ohlcv = await self.exchange.watch_ohlcv(symbol, self.timeframe)
                    price = float(ohlcv[-1][4])
                    await self.push_event(symbol, price, ohlcv)
                else:
                    trades = await self.exchange.watch_trades(symbol)
                    if trades:
                        trade = trades[-1]
                        price = float(trade["price"])
                        ohlcvc = self.exchange.build_ohlcvc([trade], self.timeframe)
                        await self.push_event(symbol, price, ohlcvc)
            except ccxtpro.NetworkError as e:
                logging.warning(f"{symbol}: network error {e}, reconnecting...")
                await asyncio.sleep(5)
            except ccxtpro.ExchangeError as e:
                logging.warning(f"{symbol}: exchange error {e}, reconnecting...")
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logging.error(f"Unexpected error for {symbol}: {e}")
                await asyncio.sleep(5)

    # ------------------------------------------------------------------- #
    #                         Event processing                            #
    # ------------------------------------------------------------------- #

    async def push_event(self, symbol, price, ohlcv):
        last = self.last_price.get(symbol)
        if last != price:
            self.last_price[symbol] = price
            await self.event_queue.put(
                {"symbol": symbol, "price": price, "ohlcv": ohlcv}
            )

    async def process_events(self):
        """Consumer that handles all incoming ticker events."""
        while self.status:
            try:
                event = await self.event_queue.get()
                symbol, price, ohlcv = event["symbol"], event["price"], event["ohlcv"]
                ticker_price = {
                    "type": "ticker_price",
                    "ticker": {"symbol": symbol, "price": price},
                }
                await asyncio.gather(
                    self.dca.process_ticker_data(ticker_price),
                    self.__write_ohlcv_data(symbol, ohlcv),
                )
            except Exception as e:
                logging.error(f"Error processing event: {e}")

    async def __write_ohlcv_data(self, symbol, ticker):
        current_candle = ticker[-1]
        if Watcher.exchange_watcher_ohlcv:
            timestamp, o, h, l, c, v = current_candle
        else:
            timestamp, o, h, l, c, v, _ = current_candle

        last = Watcher.candles.get(symbol)
        if not last or last[0] < timestamp:
            if last:
                t, o1, h1, l1, c1, v1 = last[:6]
                await model.Tickers.create(
                    timestamp=t,
                    symbol=symbol,
                    open=o1,
                    high=h1,
                    low=l1,
                    close=c1,
                    volume=v1,
                )
            Watcher.candles[symbol] = current_candle

    # ------------------------------------------------------------------- #
    #                              Shutdown                               #
    # ------------------------------------------------------------------- #

    async def shutdown(self):
        self.status = False
        for task in self.symbol_tasks.values():
            task.cancel()
        await self.exchange.close()
        logging.info("Watcher shutdown complete.")
