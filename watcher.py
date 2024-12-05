import ccxt.pro as ccxtpro
import asyncio

from logger import LoggerFactory
from models import Trades


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
        Watcher.status = True
        Watcher.dca = dca
        Watcher.tickers = tickers
        Watcher.symbols = []
        Watcher.logging = LoggerFactory.get_logger(
            "logs/dca.log", "watcher", log_level=loglevel
        )
        Watcher.logging.info("Initialized")

    def __convert_symbols(self, symbols):
        symbol_list = []
        for symbol in symbols:
            symbol_list.append([symbol, self.timeframe])
        return symbol_list

    # Get Tickers from Exchange modules (buy/sell)
    async def update_symbols(self):
        while Watcher.status:
            try:
                tickers = await Watcher.tickers.get()
                Watcher.symbols = self.__convert_symbols(tickers)
                Watcher.tickers.task_done()
                Watcher.logging.debug(f"Watching symbols: {Watcher.symbols}")
            except asyncio.QueueEmpty:
                continue

    async def watch_tickers(self):
        last_price = None

        # Initial list for symbols in database
        symbols = await Trades.all().distinct().values_list("symbol", flat=True)
        if symbols:
            Watcher.symbols = self.__convert_symbols(symbols)

        actual_symbols = Watcher.symbols
        while Watcher.status:
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
                        Watcher.logging.error(f"CCXT websocket error. Cause: {e}")
                        continue
                else:
                    actual_symbols = Watcher.symbols
                    continue
            else:
                await asyncio.sleep(5)

    async def watch_orders(self):
        while Watcher.status:
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
                continue

    async def shutdown(self):
        Watcher.status = False
        await Watcher.exchange.close()
