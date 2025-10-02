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
utils = helper.Utils()


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
        Watcher.candles = {}

    async def __write_ohlcv_data(self, symbol, ticker):
        current_candle = ticker[-1]
        timestamp, open, high, low, close, volume, check = current_candle
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
                        check,
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
                trades = await Trades().get_symbols()
                for new_symbol in new_symbol_list:
                    if new_symbol not in trades:
                        trades.append(new_symbol)
                        logging.debug(f"{new_symbol} not in trades, adding it.")
                # Watcher.ticker_symbols = utils.convert_symbols(trades)
                Watcher.ticker_symbols = trades
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
                new_symbol_list = await Trades().get_symbols()
                # Watcher.ticker_symbols = utils.convert_symbols(new_symbol_list)
                Watcher.ticker_symbols = new_symbol_list
                logging.debug(f"Added symbols. New list: {Watcher.ticker_symbols}")

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
                new_symbol_list = await Trades().get_symbols()
                # Watcher.ticker_symbols = utils.convert_symbols(new_symbol_list)
                Watcher.ticker_symbols = new_symbol_list
                logging.debug(f"Removed symbols. New list: {Watcher.ticker_symbols}")
            except Exception as e:
                logging.error(f"Error removing trade symbols from watcher. Cause: {e}")

    async def watch_tickers(self):
        last_price = {}

        # Initial list for symbols in database
        ticker_symbols = await Trades().get_symbols()

        if ticker_symbols:
            # Watcher.ticker_symbols = utils.convert_symbols(ticker_symbols)
            Watcher.ticker_symbols = ticker_symbols
            Watcher.candles = {symbol: None for symbol in ticker_symbols}

        actual_symbols = Watcher.ticker_symbols
        while self.status:
            if Watcher.ticker_symbols:
                # Reload on symbol list change
                if Watcher.ticker_symbols == actual_symbols:
                    try:
                        trades = await self.exchange.watch_trades_for_symbols(
                            Watcher.ticker_symbols
                        )
                        for trade in trades:
                            ohlcvc = self.exchange.build_ohlcvc([trade], "1m")
                            actual_price = float(ohlcvc[0][4])
                            if trade["symbol"] in last_price:
                                if float(actual_price) != float(
                                    last_price[trade["symbol"]]
                                ):
                                    ticker_price = {
                                        "type": "ticker_price",
                                        "ticker": {
                                            "symbol": trade["symbol"],
                                            "price": actual_price,
                                        },
                                    }
                                    await self.dca.process_ticker_data(ticker_price)
                                    await self.__write_ohlcv_data(
                                        trade["symbol"], ohlcvc
                                    )
                                    last_price[trade["symbol"]] = actual_price
                            else:
                                last_price[trade["symbol"]] = actual_price
                    except ccxt.NetworkError as e:
                        logging.error(
                            f"Error watching websocket data from Exchange due to a network error: {e}"
                        )
                    except ccxt.ExchangeError as e:
                        logging.error(
                            f"Error watching websocket data from Exchange due to an exchange error: {e}"
                        )
                    except ccxt.BaseError as e:
                        logging.error(
                            f"Error watching websocket data from Exchange: {e}"
                        )
                    except Exception as e:
                        logging.error(f"CCXT websocket error. Cause: {e}")
                    finally:
                        await self.exchange.close()
                        continue

                else:
                    actual_symbols = Watcher.ticker_symbols

                    continue
            else:
                await asyncio.sleep(5)

    async def shutdown(self):
        self.status = False
        await self.exchange.close()
