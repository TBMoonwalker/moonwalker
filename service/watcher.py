import ccxt.pro as ccxtpro
import ccxt as ccxt
import asyncio
import helper
from service.trades import Trades
from service.dca import Dca

logging = helper.LoggerFactory.get_logger("logs/watcher.log", "watcher")


class Watcher:
    def __init__(self):
        config = helper.Config()

        self.trades = Trades()
        self.dca = Dca()
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
        Watcher.symbols = []

    def __convert_symbols(self, symbols):
        symbol_list = []
        for symbol in symbols:
            symbol_list.append([symbol, self.timeframe])
        return symbol_list

    # Get Tickers from Exchange modules (buy/sell)
    async def get_updated_symbols(self, tickers):
        try:
            Watcher.symbols = self.__convert_symbols(tickers)
            logging.debug(f"Watching symbols: {Watcher.symbols}")
        except Exception:
            logging.error(f"Error update symbols: {tickers}. Cause: {e}")

    async def watch_tickers(self):
        last_price = {}

        # Initial list for symbols in database
        symbols = await self.trades.get_symbols()
        if symbols:
            Watcher.symbols = self.__convert_symbols(symbols)

        actual_symbols = Watcher.symbols
        while self.status:
            if Watcher.symbols:
                # Reload on symbol list change
                if Watcher.symbols == actual_symbols:
                    try:
                        tickers = await self.exchange.watch_ohlcv_for_symbols(
                            Watcher.symbols
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
                                    await self.dca.process_ticker_data(ticker_price)
                                    last_price[symbol] = actual_price
                            else:
                                last_price[symbol] = actual_price
                else:
                    actual_symbols = Watcher.symbols
                    continue
            else:
                await asyncio.sleep(5)

    async def shutdown(self):
        self.status = False
        await self.exchange.close()
