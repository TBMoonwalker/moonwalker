import ccxt.pro as ccxtpro
from asyncio import gather
import asyncio

from logger import LoggerFactory
from models import Trades


class Watcher:
    def __init__(
        self,
        dca,
        tickers,
        exchange,
        key,
        secret,
        currency,
        market,
        sandbox,
        loglevel,
        timeframe,
    ):
        self.currency = currency
        self.exchange_id = exchange
        self.exchange_class = getattr(ccxtpro, self.exchange_id)
        Watcher.exchange = self.exchange_class(
            {
                "apiKey": key,
                "secret": secret,
                "options": {
                    "defaultType": market,
                },
            },
        )
        Watcher.exchange.set_sandbox_mode(sandbox)
        self.market = market
        self.timeframe = timeframe

        # Class variables
        Watcher.dca = dca
        Watcher.tickers = tickers
        Watcher.symbols = []
        Watcher.logging = LoggerFactory.get_logger(
            "dca.log", "watcher", log_level=loglevel
        )
        Watcher.logging.info("Initialized")

    # def __convert_symbols(self, symbols):
    #     Watcher.logging.debug(symbols)
    #     if self.market == "future":
    #         converted_symbols = []
    #         for symbol in symbols:
    #             symbol = f"{symbol}:{self.currency}"
    #             converted_symbols.append(symbol)
    #     else:
    #         converted_symbols = symbols
    #     return converted_symbols

    def __convert_symbols(self, symbols):
        symbol_list = []
        for symbol in symbols:
            symbol_list.append([symbol, self.timeframe])
        return symbol_list

    # Get Tickers from Exchange modules (buy/sell)
    async def update_symbols(self):
        while True:
            try:
                tickers = await Watcher.tickers.get()
                Watcher.symbols = self.__convert_symbols(tickers)
                print(Watcher.symbols)
                # for symbol in self.symbols:
                #     asyncio.create_task(self.__ticker_loop(symbol))
            except asyncio.QueueEmpty:
                continue

    # async def __ticker_loop(self, symbol):
    #     Watcher.logging.info(f"Adding symbol: {symbol}")
    #     last_price = None
    #     await self.exchange.throttle(
    #         200 / self.exchange.rateLimit
    #     )  # 1 subscription every 200 milliseconds
    #     while True:
    #         try:
    #             ticker = await self.exchange.watch_ticker(symbol)
    #             actual_price = float(ticker["last"])
    #             if last_price:
    #                 if float(actual_price) != float(last_price):
    #                     ticker_price = {
    #                         "type": "ticker_price",
    #                         "ticker": {
    #                             "symbol": ticker["symbol"],
    #                             "price": ticker["last"],
    #                         },
    #                     }
    #                     await Watcher.dca.put(ticker_price)
    #                     last_price = actual_price
    #             else:
    #                 last_price = actual_price
    #         except Exception as e:
    #             Watcher.logging.error(
    #                 f"Error running tickers websocket stream for symbol {symbol}: {e}"
    #             )
    #             break
    #     await self.exchange.close()

    # async def watch_tickers(self):
    #     # Initial list for symbols in database
    #     symbols = await Trades.all().distinct().values_list("symbol", flat=True)
    #     if symbols:
    #         self.symbols = self.__convert_symbols(symbols)

    #     for symbol in self.symbols:
    #         asyncio.create_task(self.__ticker_loop(symbol))

    async def watch_tickers(self):
        last_price = None

        # Initial list for symbols in database
        symbols = await Trades.all().distinct().values_list("symbol", flat=True)
        if symbols:
            Watcher.symbols = self.__convert_symbols(symbols)

        actual_symbols = Watcher.symbols
        while True:
            if Watcher.symbols:
                # Reload on symbol list change
                if Watcher.symbols == actual_symbols:
                    try:
                        tickers = await Watcher.exchange.watch_ohlcv_for_symbols(
                            Watcher.symbols
                        )
                        for symbol in tickers:
                            for ticker in tickers[symbol]:
                                actual_price = float(tickers[symbol][ticker][0][4])
                                if last_price:
                                    if float(actual_price) != float(last_price):
                                        ticker_price = {
                                            "type": "ticker_price",
                                            "ticker": {
                                                "symbol": symbol,
                                                "price": actual_price,
                                            },
                                        }
                                        await Watcher.dca.put(ticker_price)
                                        last_price = actual_price
                                else:
                                    last_price = actual_price
                    except Exception as e:
                        Watcher.logging.error(e)
                        break
                else:
                    actual_symbols = Watcher.symbols
                    continue
            else:
                await asyncio.sleep(5)
        await Watcher.exchange.close()

    async def watch_orders(self):
        while True:
            try:
                orders = await Watcher.exchange.watch_orders()
                Watcher.logging.debug
                if orders[0]["trades"]:
                    order = {
                        "type": "new_order",
                        "order": {
                            "symbol": orders[0]["trades"][0]["symbol"],
                            "orderid": orders[0]["trades"][0]["order"],
                            "type": orders[0]["trades"][0]["type"],
                            "side": orders[0]["trades"][0]["side"],
                            "amount": orders[0]["trades"][0]["amount"],
                            "cost": orders[0]["trades"][0]["cost"],
                            "status": orders[0]["status"],
                        },
                    }
                    await Watcher.dca.put(order)
            except Exception as e:
                Watcher.logging.error(e)
                break
        await Watcher.exchange.close()

    async def shutdown(self):
        await Watcher.exchange.close()
