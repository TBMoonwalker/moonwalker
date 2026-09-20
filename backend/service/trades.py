"""Trade persistence and retrieval helpers."""

import os
from collections.abc import Awaitable, Iterable
from datetime import datetime, timezone
from typing import Any, TypedDict, TypeVar
from uuid import UUID

import helper
import model
from service.database import run_sqlite_write_with_retry
from service.order_payloads import format_trade_datetime, trade_datetime_from_ms
from service.order_persistence import (
    persist_closed_trade_summary,
    persist_partial_sell_execution,
    persist_tp_limit_cancellation,
)
from service.persistence_records import ClosedTradeSummaryRecord
from service.placement_intents import mark_placement_persisted_in_transaction
from service.spot_campaign_types import TradeExposureState
from service.trade_math import parse_date_to_ms
from service.trading_controls import resolve_mission_pause_fields
from tortoise.exceptions import BaseORMException
from tortoise.expressions import F
from tortoise.functions import Sum
from tortoise.models import Q
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger("logs/trades.log", "trades")
T = TypeVar("T")


class TradeStateUnavailableError(RuntimeError):
    """Raised when authoritative trade state cannot be loaded safely."""


class PartialSellExecution(TypedDict):
    """Accumulated partial-sell execution totals on an open trade."""

    sold_amount: float
    sold_proceeds: float


class UnsellableTradeState(TypedDict):
    """Unsellable remainder state carried on the open trade row."""

    is_unsellable: bool
    unsellable_reason: str | None
    unsellable_amount: float
    unsellable_min_notional: float | None
    unsellable_estimated_notional: float | None


class Trades:
    """Database access layer for trade entities."""

    CLOSED_TRADES_PAGE_SIZE = max(
        1, int(os.getenv("MOONWALKER_CLOSED_TRADES_PAGE_SIZE", "10"))
    )
    CLOSED_TRADE_SORT_FIELDS = {
        "id": "id",
        "symbol": "symbol",
        "amount": "amount",
        "cost": "cost",
        "profit": "profit",
        "profit_percent": "profit_percent",
        "so_count": "so_count",
        "open_date": "open_date",
        "close_date": "close_date",
        "close_reason": "close_reason",
    }

    @staticmethod
    def _log_db_error(message: str, exc: BaseORMException) -> None:
        """Log database access failures consistently."""
        logging.error("%s Cause: %s", message, exc)

    @staticmethod
    def _normalize_partial_sell_execution(
        open_trade: dict[str, Any] | None,
    ) -> PartialSellExecution:
        """Normalize persisted partial-sell totals from an open-trade row."""
        if not open_trade:
            return {"sold_amount": 0.0, "sold_proceeds": 0.0}
        return {
            "sold_amount": float(open_trade.get("sold_amount") or 0.0),
            "sold_proceeds": float(open_trade.get("sold_proceeds") or 0.0),
        }

    @staticmethod
    def _float_or_zero(value: Any) -> float:
        """Return a finite float or zero for partially-populated trade payloads."""
        try:
            parsed = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return parsed if parsed == parsed else 0.0

    @classmethod
    def _calculate_sellable_amount(
        cls,
        *,
        total_amount: float,
        open_trade: dict[str, Any] | None,
    ) -> float:
        """Return the currently sellable amount after partial-sell bookkeeping."""
        if not open_trade:
            return max(0.0, total_amount)

        unsellable_state = cls._extract_unsellable_state(open_trade)
        if unsellable_state["is_unsellable"]:
            return max(
                0.0, cls._float_or_zero(open_trade.get("amount") or total_amount)
            )

        partial_sell = cls._normalize_partial_sell_execution(open_trade)
        return max(0.0, total_amount - partial_sell["sold_amount"])

    @staticmethod
    def _extract_unsellable_state(
        open_trade: dict[str, Any] | None,
    ) -> UnsellableTradeState:
        """Normalize unsellable remainder state from an open-trade row."""
        if not open_trade:
            return {
                "is_unsellable": False,
                "unsellable_reason": None,
                "unsellable_amount": 0.0,
                "unsellable_min_notional": None,
                "unsellable_estimated_notional": None,
            }

        unsellable_amount = float(open_trade.get("unsellable_amount") or 0.0)
        unsellable_reason = open_trade.get("unsellable_reason")
        return {
            "is_unsellable": unsellable_amount > 0 and bool(unsellable_reason),
            "unsellable_reason": (
                str(unsellable_reason) if unsellable_reason is not None else None
            ),
            "unsellable_amount": unsellable_amount,
            "unsellable_min_notional": (
                float(open_trade["unsellable_min_notional"])
                if open_trade.get("unsellable_min_notional") is not None
                else None
            ),
            "unsellable_estimated_notional": (
                float(open_trade["unsellable_estimated_notional"])
                if open_trade.get("unsellable_estimated_notional") is not None
                else None
            ),
        }

    @staticmethod
    def _trade_entry_sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
        """Sort trade rows by the timestamp shown in their respective tables."""
        entry_value = row.get("open_date") or row.get("campaign_started_at")
        entry_ms = (
            parse_date_to_ms(str(entry_value).strip())
            if entry_value is not None
            else None
        )
        row_id = int(row.get("id") or 0)
        if entry_ms is None:
            return (1, row_id, row_id)
        return (0, entry_ms, row_id)

    @staticmethod
    def _format_timestamp_ms(timestamp_raw: Any) -> str | None:
        """Format a Unix millisecond timestamp as a stable trade date string."""
        try:
            return format_trade_datetime(trade_datetime_from_ms(float(timestamp_raw)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _apply_automation_pause_fields(
        row: dict[str, Any],
        *,
        open_trade: dict[str, Any] | None,
    ) -> None:
        """Attach normalized mission pause fields for UI and runtime consumers."""
        row.update(
            resolve_mission_pause_fields(
                open_trade=open_trade,
            )
        )

    @classmethod
    def _resolve_display_open_date(
        cls,
        *,
        order: dict[str, Any],
        baseorder: dict[str, Any] | None,
    ) -> str | None:
        """Return the original trade date to display and sort by."""
        baseorder_open_date = cls._format_timestamp_ms(
            (baseorder or {}).get("timestamp")
        )
        if baseorder_open_date:
            return baseorder_open_date
        open_date = str(order.get("open_date") or "").strip()
        return open_date or None

    @staticmethod
    def _derive_campaign_runtime_state(
        open_trade: dict[str, Any] | None,
    ) -> tuple[str | None, str | None]:
        """Resolve lifecycle/exposure from campaign truth when available."""
        lifecycle_mode = open_trade.get("lifecycle_mode") if open_trade else None
        exposure_state = open_trade.get("exposure_state") if open_trade else None
        return lifecycle_mode, exposure_state

    async def _execute_db(
        self,
        operation: Awaitable[T],
        error_message: str,
        default: T,
    ) -> T:
        """Execute a database operation and fall back to a safe default on ORM errors."""
        try:
            return await operation
        except BaseORMException as exc:
            self._log_db_error(error_message, exc)
            return default

    async def _write_db(
        self,
        operation: Awaitable[Any],
        error_message: str,
        success_message: str | None = None,
    ) -> bool:
        """Execute a write operation and log consistent success/error messages."""
        try:
            await operation
            if success_message:
                logging.debug(success_message)
            return True
        except BaseORMException as exc:
            self._log_db_error(error_message, exc)
            return False

    async def _clear_order_cache(self) -> None:
        """Clear cached trade aggregates after open-position mutations."""
        cache_clear = getattr(self._get_trades_for_orders_cached, "cache_clear", None)
        if cache_clear is not None:
            await cache_clear()

    async def invalidate_trade_caches(self) -> None:
        """Public cache invalidation seam for open-position mutations."""
        await self._clear_order_cache()

    @helper.async_ttl_cache(maxsize=1024, ttl=60)
    async def get_trade_by_ordertype(
        self, symbol: str, baseorder: bool = False
    ) -> list[dict[str, Any]]:
        """
        Gives back the specific trade entries for an
        open order (baseorder or safetyorder)
        """
        trade: list[dict[str, Any]] = []

        # Get baseorders
        if baseorder:
            trade = await self._execute_db(
                model.Trades.filter(
                    Q(baseorder=True), Q(symbol=symbol), join_type="AND"
                ).values(),
                "Error getting baseorders from database.",
                [],
            )
        # Get safetyorders
        else:
            trade = await self._execute_db(
                model.Trades.filter(
                    Q(safetyorder=True),
                    Q(baseorder=False),
                    Q(symbol=symbol),
                    join_type="AND",
                ).values(),
                "Error getting safetyorders from database.",
                [],
            )

        return trade

    async def get_open_trades_by_symbol(self, symbol: str) -> list[dict[str, Any]]:
        """Return open trades for a symbol."""
        return await self._execute_db(
            model.OpenTrades.filter(symbol=symbol).values(),
            "Error getting open trades from database.",
            [],
        )

    async def get_trades_by_symbol(self, symbol: str) -> list[dict[str, Any]]:
        """Return all trades for a symbol."""
        return await self._execute_db(
            model.Trades.filter(symbol=symbol).values(),
            "Error getting trades from database.",
            [],
        )

    @classmethod
    def _resolve_closed_trade_sort(
        cls,
        sort_key: str | None,
        sort_direction: str | None,
    ) -> str:
        """Return a safe ORM order_by expression for closed-trade paging."""
        normalized_key = str(sort_key or "id").strip().lower()
        column_name = cls.CLOSED_TRADE_SORT_FIELDS.get(normalized_key, "id")
        direction = str(sort_direction or "desc").strip().lower()
        return column_name if direction == "asc" else f"-{column_name}"

    async def get_open_trades(
        self,
        *,
        exposure_state: str = TradeExposureState.LONG_EXPOSED.value,
    ) -> list[dict[str, Any]]:
        """
        Gives back the open orders including all base
        and safetyorders
        """

        try:
            orders = await model.OpenTrades.filter(
                exposure_state=exposure_state
            ).values()
            orders = [
                order
                for order in orders
                if not (
                    float(order.get("unsellable_amount") or 0.0) > 0
                    and order.get("unsellable_reason")
                )
            ]
            symbols = [order["symbol"] for order in orders]
            if not symbols:
                return []
            baseorders = await model.Trades.filter(
                Q(baseorder=True), Q(symbol__in=symbols), join_type="AND"
            ).values()
            safetyorders = await model.Trades.filter(
                Q(safetyorder=True),
                Q(baseorder=False),
                Q(symbol__in=symbols),
                join_type="AND",
            ).values()
            base_by_symbol = {}
            for order in baseorders:
                base_by_symbol.setdefault(order["symbol"], order)

            safety_by_symbol: dict[str, list[dict]] = {}
            for order in safetyorders:
                safety_by_symbol.setdefault(order["symbol"], []).append(order)

            for order in orders:
                baseorder = base_by_symbol.get(order["symbol"])
                if baseorder:
                    order["baseorder"] = baseorder

                safety = safety_by_symbol.get(order["symbol"])
                if safety:
                    order["safetyorders"] = safety
                display_open_date = self._resolve_display_open_date(
                    order=order,
                    baseorder=baseorder,
                )
                order["open_date"] = display_open_date
                self._apply_automation_pause_fields(
                    order,
                    open_trade=order,
                )
                profit = float(order.get("profit") or 0.0)
                profit_percent = float(order.get("profit_percent") or 0.0)
                order["display_profit"] = profit
                order["display_profit_percent"] = profit_percent
            orders.sort(key=self._trade_entry_sort_key)
            return orders
        except BaseORMException as e:
            # Broad catch to keep open trades endpoint responsive.
            logging.error("Error getting open orders. Cause: %s", e)
            return []

    async def get_unsellable_trades(self) -> list[dict[str, Any]]:
        """Return archived unsellable trade remnants."""
        return await self._execute_db(
            model.UnsellableTrades.all().order_by("-id").values(),
            "Error getting unsellable trades from database.",
            [],
        )

    @staticmethod
    def _visible_closed_trades_query():
        """Return the closed-trade query for terminal user-facing history."""
        return model.ClosedTrades.all()

    async def get_closed_trades(
        self,
        page: int = 0,
        *,
        sort_key: str | None = None,
        sort_direction: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return paginated closed trades."""
        try:
            size = self.CLOSED_TRADES_PAGE_SIZE
            query = self._visible_closed_trades_query().order_by(
                self._resolve_closed_trade_sort(sort_key, sort_direction)
            )
            if page == 0:
                orders = await query.limit(size).values()
            else:
                orders = await query.offset(page).limit(size).values()
            return orders
        except BaseORMException as e:
            # Broad catch to keep closed trades endpoint responsive.
            logging.error("Error getting closed orders. Cause: %s", e)
            return []

    async def get_trade_executions(
        self,
        deal_id: str,
    ) -> list[dict[str, Any]]:
        """Return execution rows for one trade deal."""
        try:
            normalized_deal_id = str(UUID(str(deal_id)))
        except (TypeError, ValueError):
            return []
        return await self._execute_db(
            model.TradeExecutions.filter(deal_id=normalized_deal_id)
            .order_by("timestamp", "id")
            .values(),
            f"Error getting trade executions for {normalized_deal_id}.",
            [],
        )

    async def get_closed_trades_length(self) -> int:
        """Return the total number of closed trades."""
        return await self._execute_db(
            self._visible_closed_trades_query().count(),
            "Error getting closed order length.",
            0,
        )

    async def delete_unsellable_trade(self, trade_id: int) -> bool:
        """Delete an unsellable trade by its identifier."""
        deleted_count = await self._delete_summary_and_detached_executions(
            model.UnsellableTrades,
            trade_id,
            f"Error deleting unsellable trade {trade_id}.",
        )
        return deleted_count > 0

    async def delete_all_unsellable_trades(self) -> int | None:
        """Delete all unsellable trades and orphaned execution history."""

        async def _delete_all_summaries() -> int:
            async with in_transaction() as conn:
                summary_count = (
                    await model.UnsellableTrades.all().using_db(conn).count()
                )
                if summary_count == 0:
                    return 0

                eligible_rows = await conn.execute_query_dict("""
                    SELECT DISTINCT TRIM(unsellable.deal_id) AS deal_id
                    FROM unsellabletrades AS unsellable
                    WHERE unsellable.deal_id IS NOT NULL
                      AND TRIM(unsellable.deal_id) <> ''
                      AND NOT EXISTS (
                          SELECT 1
                          FROM closedtrades AS closed
                          WHERE closed.deal_id = unsellable.deal_id
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM opentrades AS open_trade
                          WHERE open_trade.deal_id = unsellable.deal_id
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM trades AS execution
                          WHERE execution.deal_id = unsellable.deal_id
                      )
                    """)
                deal_ids = [
                    str(row.get("deal_id") or "").strip()
                    for row in eligible_rows
                    if str(row.get("deal_id") or "").strip()
                ]
                deleted_count = (
                    await model.UnsellableTrades.all().using_db(conn).delete()
                )
                if deal_ids:
                    await (
                        model.TradeReplayCandles.filter(
                            deal_id__in=deal_ids,
                        )
                        .using_db(conn)
                        .delete()
                    )
                    await (
                        model.TradeExecutions.filter(
                            deal_id__in=deal_ids,
                        )
                        .using_db(conn)
                        .delete()
                    )
                return deleted_count

        try:
            return await run_sqlite_write_with_retry(
                _delete_all_summaries,
                "deleting all unsellable trades",
            )
        except BaseORMException as exc:
            self._log_db_error("Error deleting all unsellable trades.", exc)
            return None

    async def update_open_trades(self, payload: dict[str, Any], symbol: str) -> None:
        """Update open trades for a symbol."""
        if await self.get_open_trades_by_symbol(symbol):
            await self._write_db(
                model.OpenTrades.update_or_create(
                    defaults=payload,
                    symbol=symbol,
                ),
                f"Error updating SO count for {symbol}.",
            )
            await self._clear_order_cache()

    async def set_tp_limit_order(
        self,
        symbol: str,
        *,
        order_id: str,
        price: float,
        amount: float,
        placement_operation_id: str | None = None,
    ) -> bool:
        """Persist the currently armed proactive TP limit order for a symbol."""

        async def _set_tp_limit_order() -> int:
            async with in_transaction() as conn:
                updated_count = (
                    await model.OpenTrades.filter(symbol=symbol)
                    .using_db(conn)
                    .update(
                        tp_limit_order_id=order_id,
                        tp_limit_order_price=float(price),
                        tp_limit_order_amount=float(amount),
                        tp_limit_order_armed_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                if updated_count <= 0:
                    return updated_count
                await mark_placement_persisted_in_transaction(
                    placement_operation_id,
                    conn,
                )
                return updated_count

        try:
            updated_count = await run_sqlite_write_with_retry(
                _set_tp_limit_order,
                f"setting proactive TP limit order for {symbol}",
            )
        except BaseORMException as exc:
            self._log_db_error(
                f"Error setting proactive TP limit order for {symbol}.",
                exc,
            )
            return False
        if updated_count <= 0:
            logging.error(
                "Could not persist proactive TP limit order for %s: open trade missing.",
                symbol,
            )
            return False
        await self._clear_order_cache()
        return True

    async def clear_tp_limit_order(
        self,
        symbol: str,
        *,
        placement_operation_id: str | None = None,
        exchange_status: dict[str, Any] | None = None,
    ) -> bool:
        """Clear persisted proactive TP limit order metadata for a symbol."""

        try:
            updated = await persist_tp_limit_cancellation(
                symbol,
                exchange_status,
                placement_operation_id=placement_operation_id,
            )
        except BaseORMException as exc:
            self._log_db_error(
                f"Error clearing proactive TP limit order for {symbol}.",
                exc,
            )
            return False
        if updated:
            await self._clear_order_cache()
        return bool(updated)

    async def add_partial_sell_execution(
        self,
        symbol: str,
        sold_amount: float,
        sold_proceeds: float,
        sell_executions: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        """Delegate partial sell persistence to the shared write layer."""
        await persist_partial_sell_execution(
            symbol,
            sold_amount,
            sold_proceeds,
            sell_executions,
        )

    async def get_partial_sell_execution(self, symbol: str) -> tuple[float, float]:
        """Return accumulated partial sell totals (amount, proceeds)."""
        open_trade_rows = await self._execute_db(
            model.OpenTrades.filter(symbol=symbol)
            .limit(1)
            .values("sold_amount", "sold_proceeds"),
            f"Error reading partial sell execution for {symbol}.",
            [],
        )
        open_trade = open_trade_rows[0] if open_trade_rows else None
        totals = self._normalize_partial_sell_execution(open_trade)
        return totals["sold_amount"], totals["sold_proceeds"]

    async def delete_open_trades(self, symbol: str) -> None:
        """Delete open trades for a symbol."""

        async def _delete_open_trade() -> None:
            async with in_transaction() as conn:
                open_trade = (
                    await model.OpenTrades.filter(symbol=symbol).using_db(conn).first()
                )
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).delete()
                if open_trade and open_trade.deal_id:
                    await (
                        model.TradeExecutions.filter(
                            deal_id=open_trade.deal_id,
                        )
                        .using_db(conn)
                        .delete()
                    )

        try:
            await run_sqlite_write_with_retry(
                _delete_open_trade,
                f"deleting open trades for {symbol}",
            )
            logging.debug("Deleted open trade for %s.", symbol)
        except BaseORMException as exc:
            self._log_db_error(f"Error deleting open trades for {symbol}.", exc)

    async def create_closed_trades(
        self,
        payload: ClosedTradeSummaryRecord,
    ) -> None:
        """Delegate detached closed-trade summary persistence to the write layer."""
        await persist_closed_trade_summary(payload)

    async def create_unsellable_trade(self, payload: dict[str, Any]) -> None:
        """Create an archived unsellable trade entry."""
        await self._write_db(
            model.UnsellableTrades.create(**payload),
            "Error creating unsellable trade.",
        )

    async def delete_closed_trade(self, trade_id: int) -> bool:
        """Delete a closed trade by its identifier."""
        deleted_count = await self._delete_summary_and_detached_executions(
            model.ClosedTrades,
            trade_id,
            f"Error deleting closed trade {trade_id}.",
        )
        return deleted_count > 0

    async def _delete_summary_and_detached_executions(
        self,
        summary_model: type[model.ClosedTrades] | type[model.UnsellableTrades],
        trade_id: int,
        error_message: str,
    ) -> int:
        """Delete one summary row and orphaned deal executions in one transaction."""

        async def _delete_summary() -> int:
            async with in_transaction() as conn:
                summary = await summary_model.filter(id=trade_id).using_db(conn).first()
                if summary is None:
                    return 0

                deal_id = summary.deal_id
                deleted_count = (
                    await summary_model.filter(id=trade_id).using_db(conn).delete()
                )
                if deal_id:
                    linked_rows = (
                        await model.ClosedTrades.filter(deal_id=deal_id)
                        .using_db(conn)
                        .count()
                    )
                    linked_rows += (
                        await model.UnsellableTrades.filter(deal_id=deal_id)
                        .using_db(conn)
                        .count()
                    )
                    if linked_rows == 0:
                        await (
                            model.TradeReplayCandles.filter(
                                deal_id=deal_id,
                            )
                            .using_db(conn)
                            .delete()
                        )
                        await (
                            model.TradeExecutions.filter(
                                deal_id=deal_id,
                            )
                            .using_db(conn)
                            .delete()
                        )
                return deleted_count

        try:
            return await run_sqlite_write_with_retry(
                _delete_summary,
                f"deleting summary trade {trade_id}",
            )
        except BaseORMException as exc:
            self._log_db_error(error_message, exc)
            return 0

    async def get_token_amount_from_trades(self, symbol: str) -> float:
        """Return the net remaining token amount for a symbol."""
        try:
            result = (
                await model.Trades.filter(symbol=symbol)
                .annotate(total_amount=Sum(F("amount")))
                .values_list("total_amount", flat=True)
            )
            total_amount = float(result[0] or 0.0)
            open_trade_rows = (
                await model.OpenTrades.filter(symbol=symbol)
                .limit(1)
                .values(
                    "amount",
                    "sold_amount",
                    "unsellable_amount",
                    "unsellable_reason",
                )
            )
            open_trade = open_trade_rows[0] if open_trade_rows else None
            return self._calculate_sellable_amount(
                total_amount=total_amount,
                open_trade=open_trade,
            )
        except BaseORMException as e:
            # Broad catch to avoid crashing on database aggregation errors.
            logging.error("Error getting total amount from %s. Cause %s", symbol, e)
            return 0.0

    async def get_trades_for_orders(self, symbol: str) -> dict[str, Any] | None:
        """Return a briefly cached trade aggregate for read-heavy callers."""
        return await self._get_trades_for_orders_cached(symbol)

    @helper.async_ttl_cache(maxsize=2048, ttl=2)
    async def _get_trades_for_orders_cached(
        self,
        symbol: str,
    ) -> dict[str, Any] | None:
        """Cache one trade aggregate without hiding the authoritative loader."""
        return await self.get_trades_for_orders_fresh(symbol)

    async def get_trades_for_orders_fresh(
        self,
        symbol: str,
        *,
        fail_on_error: bool = False,
    ) -> dict[str, Any] | None:
        """Load authoritative trade data for locked mutation revalidation."""
        trade_data = []
        total_cost = 0
        total_amount = 0
        current_price = 0
        safetyorders = []

        try:
            trades = await self.get_trades_by_symbol(symbol)
            opentrades = await self.get_open_trades_by_symbol(symbol)
            open_trade = opentrades[0] if opentrades else None
            if opentrades:
                current_price = opentrades[0]["current_price"]
            lifecycle_mode, exposure_state = self._derive_campaign_runtime_state(
                open_trade,
            )

            baseorder = None
            latest_order = None
            for order in trades:
                amount = float(order["amount"])
                total_cost += float(order["ordersize"])
                total_amount += amount
                latest_order = order

                if bool(order.get("baseorder")):
                    if baseorder is None or float(order["timestamp"]) < float(
                        baseorder["timestamp"]
                    ):
                        baseorder = order

                # Safetyorder data
                if bool(order.get("safetyorder")) and not bool(order.get("baseorder")):
                    safetyorder = {
                        "price": order["price"],
                        "so_percentage": order["so_percentage"],
                        "ordersize": order["ordersize"],
                    }
                    safetyorders.append(safetyorder)

            if not latest_order:
                return None
            if not baseorder:
                baseorder = min(trades, key=lambda trade: float(trade["timestamp"]))

            safetyorders_count = len(safetyorders)
            unsellable_state = self._extract_unsellable_state(open_trade)
            sellable_amount = self._calculate_sellable_amount(
                total_amount=total_amount,
                open_trade=open_trade,
            )

            # For unsellable remnants, OpenTrades carries the authoritative
            # remaining amount/cost after partial close bookkeeping.
            if unsellable_state["is_unsellable"] and open_trade:
                total_amount = float(open_trade.get("amount") or total_amount)
                total_cost = float(open_trade.get("cost") or total_cost)
                sellable_amount = total_amount

            trade_data = {
                "timestamp": latest_order["timestamp"],
                "fee": latest_order["fee"],
                "total_cost": total_cost,
                "total_amount": total_amount,
                "sellable_amount": sellable_amount,
                "symbol": latest_order["symbol"],
                "deal_id": latest_order.get("deal_id"),
                "campaign_id": (
                    open_trade.get("campaign_id")
                    if open_trade and open_trade.get("campaign_id") is not None
                    else latest_order.get("campaign_id")
                ),
                "lifecycle_mode": lifecycle_mode,
                "exposure_state": exposure_state,
                "direction": latest_order["direction"],
                "side": latest_order["side"],
                "bot": latest_order["bot"],
                "bo_price": baseorder["price"],
                "current_price": current_price,
                "safetyorders": safetyorders,
                "safetyorders_count": safetyorders_count,
                "execution_count": len(trades),
                "ordertype": baseorder["ordertype"],
                "open_date": open_trade.get("open_date") if open_trade else None,
                "tp_limit_order_id": (
                    open_trade.get("tp_limit_order_id") if open_trade else None
                ),
                "tp_limit_order_price": (
                    open_trade.get("tp_limit_order_price") if open_trade else None
                ),
                "tp_limit_order_amount": (
                    open_trade.get("tp_limit_order_amount") if open_trade else None
                ),
                "tp_limit_order_armed_at": (
                    open_trade.get("tp_limit_order_armed_at") if open_trade else None
                ),
                "dca_sizing_mode": (
                    str(open_trade.get("dca_sizing_mode") or "legacy_factors")
                    if open_trade
                    else "legacy_factors"
                ),
                "dca_policy_json": (
                    open_trade.get("dca_policy_json") if open_trade else None
                ),
                "dca_reference_price": (
                    float(open_trade.get("dca_reference_price") or 0.0)
                    if open_trade
                    else 0.0
                ),
                "dca_reference_atr_percent": (
                    float(open_trade.get("dca_reference_atr_percent") or 0.0)
                    if open_trade
                    else 0.0
                ),
                "dca_next_trigger_price": (
                    float(open_trade.get("dca_next_trigger_price") or 0.0)
                    if open_trade
                    else 0.0
                ),
                "dca_last_decision_json": (
                    open_trade.get("dca_last_decision_json") if open_trade else None
                ),
                "last_transition_at": (
                    open_trade.get("last_transition_at") if open_trade else None
                ),
                "reserved_reentry_quote": (
                    float(open_trade.get("reserved_reentry_quote") or 0.0)
                    if open_trade
                    else 0.0
                ),
                "waiting_reference_price": (
                    float(open_trade.get("waiting_reference_price") or 0.0)
                    if open_trade
                    else 0.0
                ),
                "waiting_reference_amount": (
                    float(open_trade.get("waiting_reference_amount") or 0.0)
                    if open_trade
                    else 0.0
                ),
                "waiting_reference_quote": (
                    float(open_trade.get("waiting_reference_quote") or 0.0)
                    if open_trade
                    else 0.0
                ),
                "virtual_waiting_profit": (
                    float(open_trade.get("virtual_waiting_profit") or 0.0)
                    if open_trade
                    else 0.0
                ),
                "virtual_waiting_profit_percent": (
                    float(open_trade.get("virtual_waiting_profit_percent") or 0.0)
                    if open_trade
                    else 0.0
                ),
                **resolve_mission_pause_fields(
                    open_trade=open_trade,
                ),
                **unsellable_state,
            }
            return trade_data
        except BaseORMException as exc:
            logging.error(
                "Could not load authoritative trade state for %s.",
                symbol,
                exc_info=True,
            )
            if fail_on_error:
                raise TradeStateUnavailableError(
                    f"Could not load authoritative trade state for {symbol}."
                ) from exc
            return None

    async def get_trades_for_orders_authoritative(
        self,
        symbol: str,
    ) -> dict[str, Any] | None:
        """Load trade state while preserving database failure information."""
        return await self.get_trades_for_orders_fresh(symbol, fail_on_error=True)

    async def get_symbols(self) -> list[str]:
        """Return distinct trade symbols."""
        rows = await self._execute_db(
            model.OpenTrades.all().values(
                "symbol",
                "unsellable_amount",
                "unsellable_reason",
            ),
            "Error getting trade symbols.",
            [],
        )
        symbols: list[str] = []
        for row in rows:
            if float(row.get("unsellable_amount") or 0.0) > 0 and row.get(
                "unsellable_reason"
            ):
                continue
            symbol = str(row.get("symbol") or "").strip()
            if symbol:
                symbols.append(symbol)
        return symbols
