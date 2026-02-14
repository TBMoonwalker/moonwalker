"""Order orchestration for exchange buy/sell actions."""

import asyncio
import json
import time
from datetime import datetime
from typing import Any

import helper
import model
from service.database import run_sqlite_write_with_retry
from service.exchange import Exchange
from service.monitoring import MonitoringService
from service.trades import Trades
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger("logs/orders.log", "orders")


class Orders:
    """Handle incoming buy/sell signals and persist trades."""

    _sell_locks: dict[str, asyncio.Lock] = {}

    def __init__(self):
        self.utils = helper.Utils()
        self.exchange = Exchange()
        self.monitoring = MonitoringService()
        self.trades = Trades()

    @classmethod
    def _get_sell_lock(cls, symbol: str) -> asyncio.Lock:
        """Return a shared per-symbol sell lock."""
        lock = cls._sell_locks.get(symbol)
        if lock is None:
            lock = asyncio.Lock()
            cls._sell_locks[symbol] = lock
        return lock

    async def receive_sell_order(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> None:
        """Create a sell order and persist closed trades."""
        logging.info(f"Incoming sell order for {order['symbol']}")
        sell_lock = self._get_sell_lock(order["symbol"])
        if sell_lock.locked():
            logging.debug(
                "Skipping sell for %s because another sell is in progress.",
                order["symbol"],
            )
            return

        async with sell_lock:
            try:
                order["total_amount"] = await self.trades.get_token_amount_from_trades(
                    order["symbol"]
                )

                # 1. Create exchange order
                order_status = await self.exchange.create_spot_sell(order, config)

                if order_status:
                    # 2. Create closed trade
                    open_timestamp = 0.0
                    base_order = await self.trades.get_trade_by_ordertype(
                        order_status["symbol"], baseorder=True
                    )

                    try:
                        open_timestamp = float(base_order[0]["timestamp"])
                    except Exception as e:
                        # Broad catch: base order may be missing or malformed.
                        open_timestamp = datetime.timestamp(datetime.now())
                        logging.debug(
                            f"Did not found a timestamp - taking default value. Cause {e}"
                        )
                        pass

                    open_trade = await self.trades.get_open_trades_by_symbol(
                        order_status["symbol"]
                    )
                    # ToDo - why is it sometimes emtpy? Race condition?
                    so_count = 0
                    if open_trade:
                        so_count = open_trade[0]["so_count"]

                    sell_timestamp = time.mktime(datetime.now().timetuple()) * 1000
                    sell_date = datetime.now()
                    open_date = datetime.fromtimestamp((open_timestamp / 1000.0))

                    # Calculate trade duration
                    duration_data = self.__calculate_trade_duration(
                        open_timestamp, sell_timestamp
                    )
                    payload = {
                        "symbol": order_status["symbol"],
                        "so_count": so_count,
                        "profit": order_status["profit"],
                        "profit_percent": order_status["profit_percent"],
                        "amount": order_status["total_amount"],
                        "cost": order_status["total_cost"],
                        "tp_price": order_status["tp_price"],
                        "avg_price": order_status["avg_price"],
                        "open_date": open_date,
                        "close_date": sell_date,
                        "duration": duration_data,
                    }

                    async def _persist_sell() -> None:
                        async with in_transaction() as conn:
                            await model.ClosedTrades.create(**payload, using_db=conn)
                            await model.Trades.filter(symbol=order["symbol"]).using_db(
                                conn
                            ).delete()
                            await model.OpenTrades.filter(
                                symbol=order["symbol"]
                            ).using_db(conn).delete()

                    await run_sqlite_write_with_retry(
                        _persist_sell, f"persisting sell order for {order['symbol']}"
                    )
                    await self.monitoring.notify_trade(
                        "trade.sell",
                        {
                            "symbol": order_status["symbol"],
                            "side": "sell",
                            "amount": order_status["total_amount"],
                            "cost": order_status["total_cost"],
                            "avg_price": order_status["avg_price"],
                            "tp_price": order_status["tp_price"],
                            "profit": order_status["profit"],
                            "profit_percent": order_status["profit_percent"],
                            "so_count": so_count,
                            "open_date": open_date.isoformat(),
                            "close_date": sell_date.isoformat(),
                            "duration": duration_data,
                        },
                        config,
                    )
                else:
                    logging.error(f"Failed creating sell order for {order['symbol']}")
            finally:
                await self.exchange.close()

    async def receive_buy_order(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Create a buy order and persist open trades."""

        logging.info(f"Incoming buy order for {order['symbol']}")

        try:
            # 1. Create exchange order
            order_status = await self.exchange.create_spot_market_buy(order, config)
            logging.debug(order_status)
            if order_status:
                if (
                    not order_status.get("amount")
                    or float(order_status["amount"]) <= 0
                    or not order_status.get("price")
                ):
                    logging.error(
                        "Skipping trade creation for %s: invalid order status.",
                        order.get("symbol"),
                    )
                    return False
                # 2. Create trade
                payload = {
                    "timestamp": order_status["timestamp"],
                    "ordersize": order_status["ordersize"],
                    "fee": order_status["fees"],
                    "precision": order_status["precision"],
                    "amount_fee": order_status["amount_fee"],
                    "amount": order_status["amount"],
                    "price": order_status["price"],
                    "symbol": order_status["symbol"],
                    "orderid": order_status["orderid"],
                    "bot": order_status["botname"],
                    "ordertype": order_status["ordertype"],
                    "baseorder": order_status["baseorder"],
                    "safetyorder": order_status["safetyorder"],
                    "order_count": order_status["order_count"],
                    "so_percentage": order_status["so_percentage"],
                    "direction": order_status["direction"],
                    "side": order_status["side"],
                }

                async def _persist_buy() -> None:
                    async with in_transaction() as conn:
                        await model.Trades.create(**payload, using_db=conn)

                        # 3. Create open trade (only for base order)
                        if not order["safetyorder"]:
                            await model.OpenTrades.create(
                                symbol=order_status["symbol"], using_db=conn
                            )

                await run_sqlite_write_with_retry(
                    _persist_buy, f"persisting buy order for {order['symbol']}"
                )
                await self.monitoring.notify_trade(
                    "trade.buy",
                    {
                        "symbol": order_status["symbol"],
                        "side": "buy",
                        "timestamp": order_status["timestamp"],
                        "ordersize": order_status["ordersize"],
                        "price": order_status["price"],
                        "amount": order_status["amount"],
                        "bot": order_status["botname"],
                        "ordertype": order_status["ordertype"],
                        "baseorder": order_status["baseorder"],
                        "safetyorder": order_status["safetyorder"],
                        "order_count": order_status["order_count"],
                        "so_percentage": order_status["so_percentage"],
                    },
                    config,
                )
                return True
            else:
                logging.error(f"Failed creating buy order for {order['symbol']}")
                return False
        finally:
            await self.exchange.close()

    async def receive_stop_signal(self, symbol: str) -> bool:
        """Stop trading for a symbol."""
        logging.info("Incoming stop order")
        symbol = symbol.upper()
        token, currency = symbol.split("-")
        symbol = f"{token}/{currency}"
        try:

            async def _persist_stop() -> None:
                async with in_transaction() as conn:
                    await model.OpenTrades.filter(symbol=symbol).using_db(conn).delete()
                    await model.Trades.filter(symbol=symbol).using_db(conn).delete()

            await run_sqlite_write_with_retry(
                _persist_stop, f"stopping symbol {symbol}"
            )
            return True
        except Exception as e:
            logging.error(
                f"Cannot stop trade for {symbol}. See trade logs for errors. Cause: {e}"
            )
            return False

    async def receive_sell_signal(self, symbol: str, config: dict[str, Any]) -> bool:
        """Handle a manual sell signal."""
        symbol = symbol.upper()
        token, currency = symbol.split("-")
        symbol = f"{token}/{currency}"
        trades = await self.trades.get_trades_for_orders(symbol)
        actual_pnl = self.utils.calculate_actual_pnl(trades, trades["current_price"])

        if trades:
            actual_pnl = self.utils.calculate_actual_pnl(trades)

            order = {
                "symbol": trades["symbol"],
                "direction": trades["direction"],
                "side": "sell",
                "type_sell": "order_sell",
                "actual_pnl": actual_pnl,
                "total_cost": trades["total_cost"],
                "current_price": trades["current_price"],
            }

            await self.receive_sell_order(order, config)
            return True

        # If OpenTrade remove hasn't worked
        else:
            logging.error(
                f"Force remove trade from OpenTrades table for {symbol} - No running trade found."
            )
            await self.trades.delete_open_trades(symbol)
            return False

    async def receive_buy_signal(
        self, symbol: str, ordersize: float, config: dict[str, Any]
    ) -> bool:
        """Handle a manual buy signal."""
        symbol = symbol.upper()
        token, currency = symbol.split("-")
        symbol = f"{token}/{currency}"
        trades = await self.trades.get_trades_for_orders(symbol)

        if trades:
            actual_pnl = self.utils.calculate_actual_pnl(trades)
            if trades["safetyorders"]:
                safety_order_count = len(trades["safetyorders"])
            else:
                safety_order_count = 0

            order = {
                "ordersize": ordersize,
                "symbol": symbol,
                "direction": trades["direction"],
                "botname": trades["bot"],
                "baseorder": False,
                "safetyorder": True,
                "order_count": safety_order_count + 1,
                "ordertype": "market",
                "so_percentage": actual_pnl,
                "side": "buy",
            }

            await self.receive_buy_order(order, config)
            return True
        else:
            return False

    def __calculate_trade_duration(self, start_date: float, end_date: float) -> str:
        """Calculate trade duration as a JSON string."""
        # Convert Unix timestamps to datetime objects
        date1 = datetime.fromtimestamp((start_date / 1000.0))
        date2 = datetime.fromtimestamp(end_date / 1000.0)

        # Calculate the time difference
        time_difference = date2 - date1

        # Extract days, seconds, and microseconds
        days = time_difference.days
        seconds = time_difference.seconds

        # Calculate hours, minutes, and seconds
        hours, reminder = divmod(seconds, 3600)
        minutes, seconds = divmod(reminder, 60)

        return json.dumps(
            {
                "days": days,
                "hours": hours,
                "minutes": minutes,
                "seconds": seconds,
            }
        )
