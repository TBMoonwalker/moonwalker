"""Order orchestration for exchange buy/sell actions."""

import asyncio
import sqlite3
from datetime import datetime
from typing import Any, TypeGuard

import helper
from service.exchange import Exchange
from service.exchange_types import (
    ExchangeOrderPayload,
    PartialSellStatus,
    SoldCheckStatus,
)
from service.monitoring import MonitoringService
from service.order_close_context import (
    build_unsellable_remainder_context,
    build_unsellable_status_snapshot,
)
from service.order_intents import (
    build_manual_buy_order_intent,
    build_manual_sell_order_intent,
)
from service.order_payloads import (
    build_buy_monitor_payload,
    build_buy_trade_payload,
    build_closed_trade_payloads,
    build_manual_buy_open_trade_payload,
    build_manual_buy_trade_payload,
)
from service.order_persistence import (
    persist_buy_trade,
    persist_closed_trade,
    persist_manual_buy_add,
    persist_stopped_trade,
    persist_unsellable_remainder,
)
from service.order_requests import normalize_order_symbol, parse_manual_buy_add_request
from service.trade_math import calculate_order_size, calculate_so_percentage
from service.trades import Trades
from tortoise.exceptions import ConfigurationError

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
                await persist_closed_trade(order["symbol"], close_context["payload"])
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
        snapshot = build_unsellable_status_snapshot(order_status)
        if not snapshot.symbol:
            return

        open_trade_rows = await self.trades.get_open_trades_by_symbol(snapshot.symbol)
        open_trade = open_trade_rows[0] if open_trade_rows else None
        so_count = await self.__resolve_so_count(snapshot.symbol)
        open_timestamp = (
            await self.__resolve_open_timestamp(snapshot.symbol)
            if snapshot.partial_amount > 0
            else None
        )
        context = build_unsellable_remainder_context(
            snapshot,
            open_trade=open_trade,
            so_count=so_count,
            open_timestamp_ms=open_timestamp,
        )

        if context.closed_trade_payload is not None:
            await self.trades.create_closed_trades(context.closed_trade_payload)

        await persist_unsellable_remainder(
            snapshot.symbol,
            context.unsellable_payload,
        )

        if not context.already_notified:
            await self.monitoring.notify_trade(
                "trade.unsellable_notional",
                context.monitor_payload,
                config,
            )
        logging.warning(
            "Marked %s remainder as unsellable (reason=%s, remaining=%s, min_notional=%s, estimated_notional=%s).",
            context.symbol,
            context.reason,
            context.remaining_amount,
            context.min_notional,
            context.estimated_notional,
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
                await persist_buy_trade(
                    order_status["symbol"],
                    payload,
                    create_open_trade=not bool(order["safetyorder"]),
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
        request = parse_manual_buy_add_request(
            symbol=symbol,
            date_input=date_input,
            price_raw=price_raw,
            amount_raw=amount_raw,
        )
        normalized_symbol = request.symbol

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
        if request.timestamp_ms < last_timestamp:
            raise ValueError(
                "Date must be greater than or equal to the latest existing buy date."
            )

        trade_data = await self.trades.get_trades_for_orders(normalized_symbol)
        if not trade_data:
            raise ValueError(f"Cannot resolve trade context for {normalized_symbol}.")

        previous_price = float(last_trade.get("price") or 0.0)
        ordersize = calculate_order_size(price=request.price, amount=request.amount)
        so_percentage = calculate_so_percentage(
            price=request.price,
            previous_price=previous_price,
            is_base=False,
        )
        safetyorders_count = int(trade_data.get("safetyorders_count") or 0)
        order_count = safetyorders_count + 1

        trade_payload = build_manual_buy_trade_payload(
            normalized_symbol=normalized_symbol,
            timestamp_ms=request.timestamp_ms,
            price=request.price,
            amount=request.amount,
            ordersize=float(ordersize),
            amount_precision=request.amount_precision,
            order_count=order_count,
            so_percentage=so_percentage,
            trade_data=trade_data,
        )
        open_trade_payload = build_manual_buy_open_trade_payload(
            open_trade=open_trade,
            amount=request.amount,
            ordersize=float(ordersize),
            order_count=order_count,
            tp_percent=float(config.get("tp", 0.0) or 0.0),
        )

        await persist_manual_buy_add(
            normalized_symbol,
            trade_payload,
            open_trade_payload,
        )
        return {
            "symbol": normalized_symbol,
            "timestamp": request.timestamp_ms,
            "price": request.price,
            "amount": request.amount,
            "ordersize": float(ordersize),
            "so_percentage": float(so_percentage),
            "order_count": order_count,
        }

    async def receive_stop_signal(self, symbol: str) -> bool:
        """Stop trading for a symbol."""
        logging.info("Incoming stop order")
        symbol = normalize_order_symbol(symbol)
        try:
            await persist_stopped_trade(symbol)
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
        symbol = normalize_order_symbol(symbol)
        trades = await self.trades.get_trades_for_orders(symbol)
        if not trades:
            logging.error(
                "Force remove trade from OpenTrades table for %s - No running trade found.",
                symbol,
            )
            await self.trades.delete_open_trades(symbol)
            return False

        actual_pnl = self.utils.calculate_actual_pnl(trades)
        order = build_manual_sell_order_intent(trades, actual_pnl)
        await self.receive_sell_order(order, config)
        return True

    async def receive_buy_signal(
        self, symbol: str, ordersize: float, config: dict[str, Any]
    ) -> bool:
        """Handle a manual buy signal."""
        symbol = normalize_order_symbol(symbol)
        trades = await self.trades.get_trades_for_orders(symbol)

        if not trades:
            return False

        actual_pnl = self.utils.calculate_actual_pnl(trades)
        order = build_manual_buy_order_intent(symbol, ordersize, trades, actual_pnl)
        await self.receive_buy_order(order, config)
        return True
