"""Order orchestration for exchange buy/sell actions."""

import asyncio
import sqlite3
from datetime import datetime
from typing import Any, TypeGuard

import helper
import model
from service.database import run_sqlite_write_with_retry
from service.exchange import Exchange
from service.exchange_types import (
    ExchangeOrderPayload,
    PartialSellStatus,
    SoldCheckStatus,
)
from service.monitoring import MonitoringService
from service.order_payloads import (
    build_buy_monitor_payload,
    build_buy_trade_payload,
    build_closed_trade_payloads,
    build_manual_buy_open_trade_payload,
    build_manual_buy_trade_payload,
    calculate_trade_duration,
)
from service.trade_math import (
    calculate_order_size,
    calculate_so_percentage,
    count_decimal_places,
    parse_date_to_ms,
)
from service.trades import Trades
from tortoise.exceptions import ConfigurationError
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
                    logging.error(
                        "Failed creating sell order for %s. "
                        "No exchange sell result was returned.",
                        order["symbol"],
                    )
                    return

                if self._is_partial_sell_status(order_status):
                    await self.__handle_partial_sell_status(order_status, config)
                    return

                if not self._is_sold_check_status(order_status):
                    logging.error(
                        "Unsupported sell order status for %s: %s",
                        order["symbol"],
                        order_status,
                    )
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

    async def __handle_partial_sell_status(
        self, order_status: PartialSellStatus, config: dict[str, Any]
    ) -> None:
        """Persist partial sell execution while keeping the trade open."""
        if bool(order_status.get("unsellable", False)):
            await self.__handle_unsellable_remainder(order_status, config)
            return

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

    async def __handle_unsellable_remainder(
        self, order_status: PartialSellStatus, config: dict[str, Any]
    ) -> None:
        """Persist partial close and mark remaining amount as unsellable."""
        symbol = str(order_status.get("symbol", ""))
        if not symbol:
            return

        partial_amount = max(
            0.0, float(order_status.get("partial_filled_amount") or 0.0)
        )
        partial_proceeds = max(0.0, float(order_status.get("partial_proceeds") or 0.0))
        remaining_amount = max(0.0, float(order_status.get("remaining_amount") or 0.0))
        reason = str(order_status.get("unsellable_reason") or "minimum_notional")
        min_notional_raw = order_status.get("unsellable_min_notional")
        estimated_notional_raw = order_status.get("unsellable_estimated_notional")
        min_notional = float(min_notional_raw) if min_notional_raw is not None else None
        estimated_notional = (
            float(estimated_notional_raw)
            if estimated_notional_raw is not None
            else None
        )

        trade_snapshot = await self.trades.get_trades_for_orders(symbol)
        open_trade_rows = await self.trades.get_open_trades_by_symbol(symbol)
        open_trade = open_trade_rows[0] if open_trade_rows else None
        already_notified = bool(open_trade and open_trade.get("unsellable_notice_sent"))

        total_amount = (
            float(trade_snapshot.get("total_amount") or 0.0) if trade_snapshot else 0.0
        )
        total_cost = (
            float(trade_snapshot.get("total_cost") or 0.0) if trade_snapshot else 0.0
        )
        if total_amount <= 0 and open_trade:
            total_amount = float(open_trade.get("amount") or 0.0)
        if total_cost <= 0 and open_trade:
            total_cost = float(open_trade.get("cost") or 0.0)

        avg_buy_price = (total_cost / total_amount) if total_amount > 0 else 0.0
        sold_cost = avg_buy_price * partial_amount
        remaining_cost = max(0.0, total_cost - sold_cost)

        if partial_amount > 0:
            open_timestamp = await self.__resolve_open_timestamp(symbol)
            so_count = await self.__resolve_so_count(symbol)
            close_date = datetime.now()
            close_timestamp = close_date.timestamp() * 1000
            open_date = datetime.fromtimestamp((open_timestamp / 1000.0))
            duration_data = calculate_trade_duration(open_timestamp, close_timestamp)
            partial_avg_sell_price = (
                partial_proceeds / partial_amount if partial_amount > 0 else 0.0
            )
            partial_profit = partial_proceeds - sold_cost
            partial_profit_percent = (
                ((partial_avg_sell_price - avg_buy_price) / avg_buy_price) * 100
                if avg_buy_price > 0
                else 0.0
            )

            await self.trades.create_closed_trades(
                {
                    "symbol": symbol,
                    "so_count": so_count,
                    "profit": partial_profit,
                    "profit_percent": partial_profit_percent,
                    "amount": partial_amount,
                    "cost": sold_cost,
                    "tp_price": partial_avg_sell_price,
                    "avg_price": avg_buy_price,
                    "open_date": open_date,
                    "close_date": close_date,
                    "duration": duration_data,
                }
            )

        tp_percent = float(config.get("tp", 0.0) or 0.0)
        next_tp_price = (
            (remaining_cost / remaining_amount) * (1 + tp_percent / 100.0)
            if remaining_amount > 0
            else 0.0
        )
        await self.trades.update_open_trades(
            {
                "amount": remaining_amount,
                "cost": remaining_cost,
                "avg_price": (
                    (remaining_cost / remaining_amount) if remaining_amount > 0 else 0.0
                ),
                "tp_price": next_tp_price,
                "sold_amount": 0.0,
                "sold_proceeds": 0.0,
                "unsellable_amount": remaining_amount,
                "unsellable_reason": reason,
                "unsellable_min_notional": min_notional,
                "unsellable_estimated_notional": estimated_notional,
                "unsellable_since": datetime.now().isoformat(),
                "unsellable_notice_sent": True,
            },
            symbol,
        )

        if not already_notified:
            await self.monitoring.notify_trade(
                "trade.unsellable_notional",
                {
                    "symbol": symbol,
                    "side": "sell",
                    "reason": reason,
                    "partial_filled_amount": partial_amount,
                    "partial_proceeds": partial_proceeds,
                    "remaining_amount": remaining_amount,
                    "unsellable_min_notional": min_notional,
                    "unsellable_estimated_notional": estimated_notional,
                },
                config,
            )
        logging.warning(
            "Marked %s remainder as unsellable (reason=%s, remaining=%s, min_notional=%s, estimated_notional=%s).",
            symbol,
            reason,
            remaining_amount,
            min_notional,
            estimated_notional,
        )

    async def __calculate_closed_trade_stats(
        self, order_status: SoldCheckStatus
    ) -> dict[str, Any]:
        """Build closed-trade payload and monitoring payload."""
        symbol = order_status["symbol"]
        open_timestamp = await self.__resolve_open_timestamp(symbol)
        so_count = await self.__resolve_so_count(symbol)
        partial_amount, partial_proceeds = await self.trades.get_partial_sell_execution(
            symbol
        )

        return build_closed_trade_payloads(
            order_status,
            so_count=so_count,
            open_timestamp_ms=open_timestamp,
            partial_amount=partial_amount,
            partial_proceeds=partial_proceeds,
        )

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
        except (IndexError, KeyError, TypeError, ValueError) as e:
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

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize symbol into BASE/QUOTE format."""
        normalized = str(symbol or "").strip().upper().replace(" ", "")
        normalized = normalized.replace("_", "/")
        if "-" in normalized and "/" not in normalized:
            normalized = normalized.replace("-", "/")

        parts = normalized.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError("Invalid symbol. Use BASE/QUOTE format.")
        return f"{parts[0]}/{parts[1]}"

    @staticmethod
    def _parse_positive_float(value: Any, field_name: str) -> float:
        """Parse and validate positive numeric payload fields."""
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid {field_name}.") from exc
        if parsed <= 0:
            raise ValueError(f"{field_name} must be greater than 0.")
        return parsed

    @staticmethod
    def _is_partial_sell_status(
        order_status: dict[str, Any],
    ) -> TypeGuard[PartialSellStatus]:
        """Return whether an exchange sell result is a partial-sell status."""
        return str(order_status.get("type") or "") == "partial_sell"

    @staticmethod
    def _is_sold_check_status(
        order_status: dict[str, Any],
    ) -> TypeGuard[SoldCheckStatus]:
        """Return whether an exchange sell result is a finalized sell status."""
        status_type = str(order_status.get("type") or "")
        if status_type == "sold_check":
            return True
        return (
            status_type == ""
            and bool(order_status.get("symbol"))
            and bool(order_status.get("total_amount"))
        )

    @staticmethod
    def _has_valid_buy_fill(order_status: ExchangeOrderPayload) -> bool:
        """Validate that an exchange buy payload contains the core filled values."""
        return (
            bool(order_status.get("price"))
            and bool(order_status.get("amount"))
            and (float(order_status["amount"]) > 0)
        )

    async def _reset_unsellable_state(self, symbol: str) -> None:
        """Clear persisted unsellable markers after a successful buy."""
        try:
            await self.trades.update_open_trades(
                {
                    "unsellable_amount": 0.0,
                    "unsellable_reason": None,
                    "unsellable_min_notional": None,
                    "unsellable_estimated_notional": None,
                    "unsellable_since": None,
                    "unsellable_notice_sent": False,
                },
                symbol,
            )
        except (RuntimeError, ConfigurationError):
            # Tests may stub persistence without initializing DB context.
            pass

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
                if not self._has_valid_buy_fill(order_status):
                    logging.error(
                        "Skipping trade creation for %s: invalid order status.",
                        order.get("symbol"),
                    )
                    return False
                payload = build_buy_trade_payload(order_status)

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
                await self._reset_unsellable_state(order_status["symbol"])
                await self.monitoring.notify_trade(
                    "trade.buy",
                    build_buy_monitor_payload(order_status),
                    config,
                )
                return True
            else:
                precheck = self.exchange.get_last_buy_precheck_result()
                if precheck and not bool(precheck.get("ok", False)):
                    logging.warning(
                        "Skipping buy order for %s: funds pre-check failed (%s). required=%s available=%s",
                        order["symbol"],
                        precheck.get("reason", "unknown"),
                        precheck.get("required_quote"),
                        precheck.get("available_quote"),
                    )
                else:
                    logging.error("Failed creating buy order for %s", order["symbol"])
                return False
        finally:
            await self.exchange.close()

    async def receive_manual_buy_add(
        self,
        symbol: str,
        date_input: Any,
        price_raw: Any,
        amount_raw: Any,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Append a manual buy as a safety-order row without exchange execution."""
        normalized_symbol = self._normalize_symbol(symbol)
        price = self._parse_positive_float(price_raw, "price")
        amount = self._parse_positive_float(amount_raw, "amount")
        timestamp_ms = parse_date_to_ms(str(date_input or "").strip())
        if timestamp_ms is None:
            raise ValueError("Invalid date.")

        open_trade_rows = await self.trades.get_open_trades_by_symbol(normalized_symbol)
        if not open_trade_rows:
            raise ValueError(f"No open trade found for {normalized_symbol}.")
        open_trade = open_trade_rows[0]

        existing_trades = await self.trades.get_trades_by_symbol(normalized_symbol)
        if not existing_trades:
            raise ValueError(f"No existing trade rows found for {normalized_symbol}.")

        last_trade = max(
            existing_trades,
            key=lambda trade: float(trade.get("timestamp") or 0.0),
        )
        last_timestamp = int(float(last_trade.get("timestamp") or 0.0))
        if int(timestamp_ms) < last_timestamp:
            raise ValueError(
                "Date must be greater than or equal to the latest existing buy date."
            )

        trade_data = await self.trades.get_trades_for_orders(normalized_symbol)
        if not trade_data:
            raise ValueError(f"Cannot resolve trade context for {normalized_symbol}.")

        previous_price = float(last_trade.get("price") or 0.0)
        ordersize = calculate_order_size(price=price, amount=amount)
        so_percentage = calculate_so_percentage(
            price=price,
            previous_price=previous_price,
            is_base=False,
        )
        safetyorders_count = int(trade_data.get("safetyorders_count") or 0)
        order_count = safetyorders_count + 1
        amount_precision = count_decimal_places(str(amount_raw))

        trade_payload = build_manual_buy_trade_payload(
            normalized_symbol=normalized_symbol,
            timestamp_ms=int(timestamp_ms),
            price=float(price),
            amount=float(amount),
            ordersize=float(ordersize),
            amount_precision=amount_precision,
            order_count=order_count,
            so_percentage=so_percentage,
            trade_data=trade_data,
        )
        open_trade_payload = build_manual_buy_open_trade_payload(
            open_trade=open_trade,
            amount=float(amount),
            ordersize=float(ordersize),
            order_count=order_count,
            tp_percent=float(config.get("tp", 0.0) or 0.0),
        )

        async def _persist_manual_buy() -> None:
            async with in_transaction() as conn:
                await model.Trades.create(**trade_payload, using_db=conn)
                updated = (
                    await model.OpenTrades.filter(symbol=normalized_symbol)
                    .using_db(conn)
                    .update(**open_trade_payload)
                )
                if updated == 0:
                    raise ValueError(f"No open trade found for {normalized_symbol}.")

        await run_sqlite_write_with_retry(
            _persist_manual_buy, f"persisting manual buy add for {normalized_symbol}"
        )
        return {
            "symbol": normalized_symbol,
            "timestamp": int(timestamp_ms),
            "price": float(price),
            "amount": float(amount),
            "ordersize": float(ordersize),
            "so_percentage": float(so_percentage),
            "order_count": order_count,
        }

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
        except (
            ConfigurationError,
            RuntimeError,
            TypeError,
            ValueError,
            OSError,
            sqlite3.Error,
        ) as e:
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
