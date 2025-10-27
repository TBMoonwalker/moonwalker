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
    #               1️⃣ Queue-based external symbol updates               #
    # ------------------------------------------------------------------- #

    async def watch_incoming_symbols(self, watcher_queue: asyncio.Queue):
        """
        Listen for symbol list updates from other parts of the app.
        This runs as a background task (started from app.py).
        """
        logging.info("Started watching incoming symbol updates...")
        while self.status:
            try:
                new_symbol_list = await watcher_queue.get()

                # Merge with current trades (so we don’t lose existing ones)
                trades = await self.trades.get_symbols()
                for new_symbol in new_symbol_list:
                    if new_symbol not in trades:
                        trades.append(new_symbol)
                        logging.debug(f"Added new symbol from queue: {new_symbol}")

                if Watcher.exchange_watcher_ohlcv:
                    trades = utils.convert_symbols(trades)

                Watcher.ticker_symbols = trades
                logging.info(f"Updated symbol list via queue: {Watcher.ticker_symbols}")

                # Notify the main watcher loop
                if Watcher.symbol_update_event:
                    Watcher.symbol_update_event.set()

                watcher_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Error in watch_incoming_symbols: {e}")
                await asyncio.sleep(2)

        logging.info("Stopped watching incoming symbol updates.")

    # ------------------------------------------------------------------- #
    #               2️⃣ ORM post_save hooks for Trades tables             #
    # ------------------------------------------------------------------- #

    @post_save(model.Trades)
    async def watch_trade_symbols(
        sender: type[model.Trades],
        instance: model.Trades,
        created: bool,
        using_db: BaseDBAsyncClient | None,
        update_fields: list[str],
    ) -> None:
        """Triggered when a new trade is opened."""
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
        """Triggered when a trade is closed."""
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
    #                        3️⃣ Main watch loop                         #
    # ------------------------------------------------------------------- #

    async def watch_tickers(self):
        """Main entrypoint for managing symbol watcher tasks."""
        logging.info("Starting Watcher...")

        Watcher.ticker_symbols = await self.trades.get_symbols()
        if Watcher.exchange_watcher_ohlcv:
            Watcher.ticker_symbols = utils.convert_symbols(Watcher.ticker_symbols)

        # Start consumer for DCA + DB writes
        consumer_task = asyncio.create_task(self.process_events())

        while self.status:
            try:
                # Start/stop per-symbol watcher tasks
                await self.sync_symbol_tasks()

                # Wait for either DB signal or queue signal
                await asyncio.wait_for(Watcher.symbol_update_event.wait(), timeout=30)
                Watcher.symbol_update_event.clear()

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logging.error(f"Error in main watcher loop: {e}")
                await asyncio.sleep(5)

        # Cleanup
        for task in self.symbol_tasks.values():
            task.cancel()
        await self.exchange.close()
        await consumer_task

    async def sync_symbol_tasks(self):
        """Compare active vs current symbols and update watchers."""
        current_symbols = set(self.symbol_tasks.keys())
        new_symbols = set(Watcher.ticker_symbols)

        # Add new
        for symbol in new_symbols - current_symbols:
            logging.info(f"Adding new symbol watcher: {symbol}")
            Watcher.candles.setdefault(symbol, None)
            task = asyncio.create_task(self.watch_symbol(symbol))
            self.symbol_tasks[symbol] = task

        # Remove old
        for symbol in current_symbols - new_symbols:
            logging.info(f"Removing symbol watcher: {symbol}")
            self.symbol_tasks[symbol].cancel()
            del self.symbol_tasks[symbol]
            Watcher.candles.pop(symbol, None)
            self.last_price.pop(symbol, None)

    # ------------------------------------------------------------------- #
    #                    4️⃣ Symbol-specific watchers                     #
    # ------------------------------------------------------------------- #

    async def watch_symbol(self, symbol: str):
        """Run websocket stream for one symbol."""
        logging.info(f"Started watcher for {symbol}")
        try:
            while self.status:
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
        except asyncio.CancelledError:
            logging.info(f"Watcher cancelled for {symbol}")
        except Exception as e:
            logging.error(f"Error in watcher for {symbol}: {e}")
            await asyncio.sleep(2)

    async def push_event(self, symbol, price, ohlcv):
        """Enqueue price update if it changed."""
        last = self.last_price.get(symbol)
        if last != price:
            self.last_price[symbol] = price
            await self.event_queue.put(
                {"symbol": symbol, "price": price, "ohlcv": ohlcv}
            )

    # ------------------------------------------------------------------- #
    #                     5️⃣ Processing of events                        #
    # ------------------------------------------------------------------- #

    async def process_events(self):
        """Consumer for ticker events — handles DCA and DB writes."""
        while self.status:
            try:
                event = await self.event_queue.get()
                symbol, price, ohlcv = (
                    event["symbol"],
                    event["price"],
                    event["ohlcv"],
                )
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
            timestamp, open_, high, low, close, volume = current_candle
        else:
            timestamp, open_, high, low, close, volume, _ = current_candle

        last = Watcher.candles.get(symbol)
        if not last or last[0] < timestamp:
            if last:
                t, o, h, l, c, v = last[:6]
                await model.Tickers.create(
                    timestamp=t,
                    symbol=symbol,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=v,
                )
            Watcher.candles[symbol] = current_candle

    # ------------------------------------------------------------------- #
    #                         6️⃣ Shutdown                                #
    # ------------------------------------------------------------------- #

    async def shutdown(self):
        self.status = False
        for task in self.symbol_tasks.values():
            task.cancel()
        await self.exchange.close()
        logging.info("Watcher shutdown complete.")
