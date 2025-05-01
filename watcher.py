import ccxt.pro as ccxtpro
import ccxt as ccxt
import asyncio

from data import Data
from logger import LoggerFactory


class Watcher:
    def __init__(
        self,
        dca,
        tickers,
        dynamic_dca,
        exchange,
        key,
        secret,
        currency,
        market,
        sandbox,
        loglevel,
        timeframe,
    ):
        self.dynamic_dca = dynamic_dca
        self.currency = currency
        self.data = Data(loglevel)
        self.exchange_id = exchange
        self.exchange_class = getattr(ccxtpro, self.exchange_id)
        self.exchange = self.exchange_class(
            {
                "apiKey": key,
                "secret": secret,
                "options": {
                    "defaultType": market,
                },
            },
        )
        self.exchange.set_sandbox_mode(sandbox)
        self.market = market
        self.timeframe = timeframe

        # Class variables
        self.status = True
        self.dca = dca
        self.tickers = tickers
        self.symbols = []
        self.logging = LoggerFactory.get_logger(
            "logs/dca.log", "watcher", log_level=loglevel
        )
        self.logging.info("Initialized")

    def __convert_symbols(self, symbols):
        symbol_list = []
        for symbol in symbols:
            symbol_list.append([symbol, self.timeframe])
        return symbol_list

    # Get Tickers from Exchange modules (buy/sell)
    async def update_symbols(self):
        while self.status:
            try:
                tickers = await self.tickers.get()
                self.symbols = self.__convert_symbols(tickers)
                self.tickers.task_done()
                self.logging.debug(f"Watching symbols: {self.symbols}")
            except asyncio.QueueEmpty:
                continue

    async def watch_tickers(self):
        last_price = {}

        # Initial list for symbols in database
        symbols = await self.data.get_symbols()
        if symbols:
            self.symbols = self.__convert_symbols(symbols)

        actual_symbols = self.symbols
        while self.status:
            if self.symbols:
                # Reload on symbol list change
                if self.symbols == actual_symbols:
                    try:
                        tickers = await self.exchange.watch_ohlcv_for_symbols(
                            self.symbols
                        )
                    except ccxt.NetworkError as e:
                        self.logging.error(
                            f"Error watching websocket data from Exchange due to a network error: {e}"
                        )
                        continue
                    except ccxt.ExchangeError as e:
                        self.logging.error(
                            f"Error watching websocket data from Exchange due to a exchange error: {e}"
                        )
                        continue
                    except ccxt.BaseError as e:
                        self.logging.error(
                            f"Error watching websocket data from Exchange: {e}"
                        )
                        continue
                    except Exception as e:
                        self.logging.error(f"CCXT websocket error. Cause: {e}")
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
                                    await self.dca.put(ticker_price)
                                    last_price[symbol] = actual_price
                            else:
                                last_price[symbol] = actual_price
                else:
                    actual_symbols = self.symbols
                    continue
            else:
                await asyncio.sleep(5)

    async def watch_orders(self):
        while self.status:
            try:
                orders = await self.exchange.watch_orders()
                self.logging.debug(orders)
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
                    await self.dca.put(order)
            except Exception as e:
                self.logging.error(e)
                continue

    async def shutdown(self):
        self.status = False
        await self.exchange.close()
