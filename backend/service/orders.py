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
        logging.info("Incoming sell order for %s", order["symbol"])
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

                if not order_status:
                    logging.error("Failed creating sell order for %s", order["symbol"])
                    return

                if await self.__handle_partial_sell_status(order_status):
                    return

                close_context = await self.__calculate_closed_trade_stats(order_status)
                await self.__persist_closed_trade(
                    order["symbol"], close_context["payload"]
                )
                await self.monitoring.notify_trade(
                    "trade.sell",
                    close_context["monitor_payload"],
                    config,
                )
            finally:
                await self.exchange.close()

    async def __handle_partial_sell_status(self, order_status: dict[str, Any]) -> bool:
        """Persist partial sell execution and return True when trade remains open."""
        if order_status.get("type") != "partial_sell":
            return False

        partial_amount = float(order_status.get("partial_filled_amount") or 0.0)
        partial_proceeds = float(order_status.get("partial_proceeds") or 0.0)
        if partial_amount > 0:
            await self.trades.add_partial_sell_execution(
                order_status["symbol"],
                partial_amount,
                partial_proceeds,
            )
            logging.info(
                "Persisted partial sell execution for %s: amount=%s proceeds=%s remaining=%s",
                order_status["symbol"],
                partial_amount,
                partial_proceeds,
                float(order_status.get("remaining_amount") or 0.0),
            )
        return True

    async def __calculate_closed_trade_stats(
        self, order_status: dict[str, Any]
    ) -> dict[str, Any]:
        """Build closed-trade payload and monitoring payload."""
        symbol = order_status["symbol"]
        open_timestamp = await self.__resolve_open_timestamp(symbol)
        so_count = await self.__resolve_so_count(symbol)
        partial_amount, partial_proceeds = await self.trades.get_partial_sell_execution(
            symbol
        )

        final_amount = float(order_status.get("total_amount") or 0.0)
        final_price = float(order_status.get("price") or 0.0)
        total_amount = partial_amount + final_amount
        total_proceeds = partial_proceeds + (final_amount * final_price)
        total_cost = float(order_status.get("total_cost") or 0.0)

        if total_amount > 0:
            avg_sell_price = total_proceeds / total_amount
            avg_buy_price = total_cost / total_amount if total_cost else 0.0
            profit = total_proceeds - total_cost
            profit_percent = (
                ((avg_sell_price - avg_buy_price) / avg_buy_price) * 100
                if avg_buy_price > 0
                else 0.0
            )
            order_status["total_amount"] = total_amount
            order_status["price"] = avg_sell_price
            order_status["tp_price"] = avg_sell_price
            order_status["avg_price"] = avg_buy_price
            order_status["profit"] = profit
            order_status["profit_percent"] = profit_percent

        sell_timestamp = time.mktime(datetime.now().timetuple()) * 1000
        sell_date = datetime.now()
        open_date = datetime.fromtimestamp((open_timestamp / 1000.0))
        duration_data = self.__calculate_trade_duration(open_timestamp, sell_timestamp)

        payload = {
            "symbol": symbol,
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
        monitor_payload = {
            "symbol": symbol,
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
        }
        return {"payload": payload, "monitor_payload": monitor_payload}

    async def __persist_closed_trade(
        self, symbol: str, payload: dict[str, Any]
    ) -> None:
        """Persist closed trade and remove open trade rows transactionally."""

        async def _persist_sell() -> None:
            async with in_transaction() as conn:
                await model.ClosedTrades.create(**payload, using_db=conn)
                await model.Trades.filter(symbol=symbol).using_db(conn).delete()
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).delete()

        await run_sqlite_write_with_retry(
            _persist_sell, f"persisting sell order for {symbol}"
        )

    async def __resolve_open_timestamp(self, symbol: str) -> float:
        """Resolve base-order timestamp for trade duration calculation."""
        base_order = await self.trades.get_trade_by_ordertype(symbol, baseorder=True)
        try:
            return float(base_order[0]["timestamp"])
        except Exception as e:
            logging.debug(
                "Did not found a timestamp - taking default value. Cause %s", e
            )
            return datetime.timestamp(datetime.now())

    async def __resolve_so_count(self, symbol: str) -> int:
        """Resolve safety-order count from open trade row."""
        open_trade = await self.trades.get_open_trades_by_symbol(symbol)
        if open_trade:
            return int(open_trade[0]["so_count"])
        return 0

    async def receive_buy_order(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Create a buy order and persist open trades."""

        logging.info("Incoming buy order for %s", order["symbol"])

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
                logging.error("Failed creating buy order for %s", order["symbol"])
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
                "Cannot stop trade for %s. See trade logs for errors. Cause: %s",
                symbol,
                e,
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
                "Force remove trade from OpenTrades table for %s - No running trade found.",
                symbol,
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
