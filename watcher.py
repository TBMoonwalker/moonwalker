import ccxt.pro as ccxtpro
import asyncio

from logger import Logger
from models import Trades


class Watcher:
    def __init__(self, dca, tickers, exchange, key, secret, currency, market, sandbox):
        self.dca = dca
        self.tickers = tickers
        self.currency = currency
        self.symbols = ["ETH/USDT:USDT"]
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

        # Logging
        self.logging = Logger("main")
        self.logging.info("Websocket module: Initialize websocket connection")

    def __convert_symbols(self, symbols):
        self.logging.debug(symbols)
        if self.market == "future":
            converted_symbols = []
            for symbol in symbols:
                symbol = f"{symbol}:{self.currency}"
                converted_symbols.append(symbol)
        else:
            converted_symbols = symbols
        return converted_symbols

    # Get Tickers from Exchange modules (buy/sell)
    async def update_symbols(self):
        while True:
            try:
                tickers = await self.tickers.get()
                self.symbols = self.__convert_symbols(tickers)
            except asyncio.QueueEmpty:
                continue

    async def watch_tickers(self):
        last_price = None

        # Initial list for symbols in database
        symbols = await Trades.all().distinct().values_list("symbol", flat=True)
        if symbols:
            self.symbols = self.__convert_symbols(symbols)

        while True:
            try:
                tickers = await self.exchange.watch_tickers(self.symbols)
                for symbol in tickers:
                    actual_price = float(tickers[symbol]["last"])
                    if last_price:
                        if float(actual_price) != float(last_price):
                            # self.logging.debug(
                            #    f"Actual price changed for symbol {tickers[symbol]['symbol']}:  {tickers[symbol]['last']}"
                            # )
                            ticker_price = {
                                "type": "ticker_price",
                                "ticker": {
                                    "symbol": tickers[symbol]["symbol"],
                                    "price": tickers[symbol]["last"],
                                },
                            }
                            await self.dca.put(ticker_price)
                            last_price = actual_price
                    else:
                        last_price = actual_price
            except Exception as e:
                self.logging.error(e)

    async def watch_orders(self):
        while True:
            try:
                orders = await self.exchange.watch_orders()
                self.logging.debug
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
                break
        await self.exchange.close()

    async def shutdown(self):
        await self.exchange.close()
