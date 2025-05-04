import ccxt.pro as ccxtpro
import ccxt as ccxt
import asyncio
import helper
import model
from service.trades import Trades
from service.dca import Dca
from service.data import Data
from tortoise import BaseDBAsyncClient
from tortoise.signals import post_save

logging = helper.LoggerFactory.get_logger("logs/watcher.log", "watcher")


class Watcher:
    def __init__(self):
        config = helper.Config()

        self.trades = Trades()
        self.dca = Dca()
        self.data = Data()
        self.dynamic_dca = config.get("dynamic_dca", False)
        self.exchange_id = config.get("exchange")
        self.exchange_class = getattr(ccxtpro, self.exchange_id)
        self.exchange = self.exchange_class(
            {
                "apiKey": config.get("key"),
                "secret": config.get("secret"),
                "options": {
                    "defaultType": config.get("market", "spot"),
                },
            },
        )
        self.exchange.set_sandbox_mode(config.get("sandbox", False))
        self.market = config.get("market", "spot")
        self.timeframe = config.get("timeframe", "1m")
        self.status = True

        # Class Variables
        Watcher.ticker_symbols = []
        Watcher.trade_symbols = []
        Watcher.candles = {}

    def __convert_symbols(self, symbols):
        symbol_list = []
        for symbol in symbols:
            symbol_list.append([symbol, self.timeframe])
        return symbol_list

    async def __write_ohlcv_data(self, symbol, ticker):
        current_candle = ticker[-1]
        timestamp, open, high, low, close, volume = current_candle
        if symbol in Watcher.candles:
            if (
                Watcher.candles[symbol] is None
                or Watcher.candles[symbol][0] < timestamp
            ):
                # The previous candle for this symbol has closed; write it to the database
                if Watcher.candles[symbol]:
                    (
                        timestamp,
                        open,
                        high,
                        low,
                        close,
                        volume,
                    ) = Watcher.candles[symbol]
                    ohlcv = {
                        "timestamp": timestamp,
                        "symbol": symbol,
                        "open": open,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                    }
                    logging.debug(ohlcv)
                    await model.Tickers.create(**ohlcv)
                Watcher.candles[symbol] = current_candle
        # Add new initial symbol for candle
        else:
            Watcher.candles[symbol] = None

    # Get new Ticker symbols from signal plugin
    async def watch_incoming_symbols(self, watcher_queue):
        current_symbols = []
        while self.status:
            try:
                new_symbol_list = await watcher_queue.get()
                # Take care of running trades
                for trade in Watcher.trade_symbols:
                    if trade not in new_symbol_list:
                        new_symbol_list.append(trade)
                        logging.debug(
                            f"{trade} not in new watchlist anymore, adding it."
                        )
                Watcher.ticker_symbols = self.__convert_symbols(new_symbol_list)
                logging.debug(f"Watching ticker symbols: {Watcher.ticker_symbols}")
                watcher_queue.task_done()
            except asyncio.QueueEmpty:
                continue

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
                Watcher.trade_symbols = await Trades().get_symbols()
                logging.debug(
                    f"Adding trade symbols to watcher: {Watcher.trade_symbols}"
                )
            except Exception as e:
                logging.error(f"Error adding trade symbols to watcher. Cause: {e}")

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
                Watcher.trade_symbols = await Trades().get_symbols()
                logging.debug(
                    f"Remove trade symbols from watcher: {Watcher.trade_symbols}"
                )
            except Exception as e:
                logging.error(f"Error removing trade symbols from watcher. Cause: {e}")

    async def watch_tickers(self):
        last_price = {}

        # Initial list for symbols in database
        ticker_symbols = await self.data.get_ticker_symbol_list()
        Watcher.trade_symbols = await self.trades.get_symbols()

        if ticker_symbols:
            Watcher.ticker_symbols = self.__convert_symbols(ticker_symbols)
            Watcher.candles = {symbol: None for symbol in ticker_symbols}

        actual_symbols = Watcher.ticker_symbols
        while self.status:
            if Watcher.ticker_symbols:
                # Reload on symbol list change
                if Watcher.ticker_symbols == actual_symbols:
                    try:
                        tickers = await self.exchange.watch_ohlcv_for_symbols(
                            Watcher.ticker_symbols
                        )
                    except ccxt.NetworkError as e:
                        logging.error(
                            f"Error watching websocket data from Exchange due to a network error: {e}"
                        )
                        continue
                    except ccxt.ExchangeError as e:
                        logging.error(
                            f"Error watching websocket data from Exchange due to a exchange error: {e}"
                        )
                        continue
                    except ccxt.BaseError as e:
                        logging.error(
                            f"Error watching websocket data from Exchange: {e}"
                        )
                        continue
                    except Exception as e:
                        logging.error(f"CCXT websocket error. Cause: {e}")
                        continue
                    for symbol in tickers:
                        for ticker in tickers[symbol]:
                            actual_price = float(tickers[symbol][ticker][0][4])
                            if symbol in last_price:
                                if float(actual_price) != float(last_price[symbol]):
                                    ticker_price = {
                                        "type": "ticker_price",
                                        "ticker": {
                                            "symbol": symbol,
                                            "price": actual_price,
                                        },
                                    }
                                    if symbol in Watcher.trade_symbols:
                                        await self.dca.process_ticker_data(ticker_price)
                                    await self.__write_ohlcv_data(
                                        symbol, tickers[symbol][ticker]
                                    )
                                    last_price[symbol] = actual_price
                            else:
                                last_price[symbol] = actual_price
                else:
                    actual_symbols = Watcher.ticker_symbols
                    continue
            else:
                await asyncio.sleep(5)

    async def shutdown(self):
        self.status = False
        await self.exchange.close()
