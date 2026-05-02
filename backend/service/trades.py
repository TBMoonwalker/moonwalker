"""Trade persistence and retrieval helpers."""

import os
from collections.abc import Awaitable, Iterable
from datetime import datetime, timezone
from typing import Any, TypedDict, TypeVar
from uuid import UUID, uuid4

import helper
import model
from service.database import run_sqlite_write_with_retry
from service.spot_campaign_types import (
    NON_TERMINAL_CLOSE_REASON_VALUES,
    TradeExposureState,
)
from service.trade_math import parse_date_to_ms
from tortoise.exceptions import BaseORMException
from tortoise.expressions import F
from tortoise.functions import Sum
from tortoise.models import Q
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger("logs/trades.log", "trades")
T = TypeVar("T")


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

    @classmethod
    def _apply_campaign_profit_fields(
        cls,
        row: dict[str, Any],
        campaign: dict[str, Any] | None,
    ) -> None:
        """Attach campaign-wide live PnL fields for UI read models.

        These fields intentionally do not replace the stored `profit` / `cost`
        accounting values on `OpenTrades`. The dashboard and capital services
        still rely on those fields as economic truth for the currently exposed
        leg, while the tables need a mission-level progress view.
        """
        is_waiting = (
            str(row.get("exposure_state") or "")
            == TradeExposureState.FLAT_WAITING_REENTRY.value
        )
        principal_quote = cls._float_or_zero((campaign or {}).get("principal_quote"))
        realized_profit = cls._float_or_zero(
            (campaign or {}).get("cumulative_realized_quote")
        )
        realized_profit_percent = cls._float_or_zero(
            (campaign or {}).get("cumulative_realized_percent")
        )
        live_delta = cls._float_or_zero(
            row.get("virtual_waiting_profit") if is_waiting else row.get("profit")
        )
        fallback_percent = cls._float_or_zero(
            row.get("virtual_waiting_profit_percent")
            if is_waiting
            else row.get("profit_percent")
        )
        total_profit = realized_profit + live_delta
        total_profit_percent = (
            (total_profit / principal_quote) * 100 if principal_quote > 0 else 0.0
        )
        if principal_quote <= 0:
            principal_quote = cls._float_or_zero(row.get("cost"))
            if principal_quote <= 0 and is_waiting:
                principal_quote = cls._float_or_zero(row.get("waiting_reference_quote"))
            total_profit_percent = fallback_percent

        row["campaign_principal_quote"] = principal_quote
        row["campaign_realized_profit"] = realized_profit
        row["campaign_realized_profit_percent"] = realized_profit_percent
        row["campaign_total_profit"] = total_profit
        row["campaign_total_profit_percent"] = total_profit_percent
        row["display_profit"] = total_profit
        row["display_profit_percent"] = total_profit_percent

    @staticmethod
    def _trade_entry_sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
        """Sort active trades by the entry timestamp shown in the UI."""
        entry_value = row.get("campaign_started_at") or row.get("open_date")
        entry_ms = (
            parse_date_to_ms(str(entry_value).strip())
            if entry_value is not None
            else None
        )
        row_id = int(row.get("id") or 0)
        if entry_ms is None:
            return (1, row_id, row_id)
        return (0, entry_ms, row_id)

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
        cache_clear = getattr(self.get_trades_for_orders, "cache_clear", None)
        if cache_clear is not None:
            await cache_clear()

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

    @staticmethod
    def _build_flat_waiting_trade_data(
        symbol: str,
        open_trade: dict[str, Any],
    ) -> dict[str, Any]:
        """Return active-flat trade context when no live exposure legs exist."""
        transition_timestamp = str(
            open_trade.get("last_transition_at")
            or open_trade.get("open_date")
            or datetime.now(timezone.utc).timestamp() * 1000
        )
        return {
            "timestamp": transition_timestamp,
            "fee": 0.0,
            "total_cost": 0.0,
            "total_amount": 0.0,
            "symbol": symbol,
            "deal_id": open_trade.get("deal_id"),
            "campaign_id": open_trade.get("campaign_id"),
            "lifecycle_mode": open_trade.get("lifecycle_mode"),
            "exposure_state": open_trade.get("exposure_state"),
            "direction": "long",
            "side": "buy",
            "bot": f"sidestep_{symbol}",
            "bo_price": 0.0,
            "current_price": float(open_trade.get("current_price") or 0.0),
            "safetyorders": [],
            "safetyorders_count": 0,
            "ordertype": "market",
            "open_date": open_trade.get("open_date"),
            "last_transition_at": open_trade.get("last_transition_at"),
            "tp_limit_order_id": None,
            "tp_limit_order_price": None,
            "tp_limit_order_amount": None,
            "tp_limit_order_armed_at": None,
            "reserved_reentry_quote": float(
                open_trade.get("reserved_reentry_quote") or 0.0
            ),
            "waiting_reference_price": float(
                open_trade.get("waiting_reference_price") or 0.0
            ),
            "waiting_reference_amount": float(
                open_trade.get("waiting_reference_amount") or 0.0
            ),
            "waiting_reference_quote": float(
                open_trade.get("waiting_reference_quote") or 0.0
            ),
            "virtual_waiting_profit": float(
                open_trade.get("virtual_waiting_profit") or 0.0
            ),
            "virtual_waiting_profit_percent": float(
                open_trade.get("virtual_waiting_profit_percent") or 0.0
            ),
            "campaign_principal_quote": 0.0,
            "campaign_realized_profit": 0.0,
            "campaign_realized_profit_percent": 0.0,
            "campaign_total_profit": float(
                open_trade.get("virtual_waiting_profit") or 0.0
            ),
            "campaign_total_profit_percent": float(
                open_trade.get("virtual_waiting_profit_percent") or 0.0
            ),
            "display_profit": float(open_trade.get("virtual_waiting_profit") or 0.0),
            "display_profit_percent": float(
                open_trade.get("virtual_waiting_profit_percent") or 0.0
            ),
            "is_unsellable": False,
            "unsellable_reason": None,
            "unsellable_amount": 0.0,
            "unsellable_min_notional": None,
            "unsellable_estimated_notional": None,
        }

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
            campaign_ids = [
                str(order.get("campaign_id") or "").strip()
                for order in orders
                if str(order.get("campaign_id") or "").strip()
            ]

            baseorders = await model.Trades.filter(
                Q(baseorder=True), Q(symbol__in=symbols), join_type="AND"
            ).values()
            safetyorders = await model.Trades.filter(
                Q(safetyorder=True),
                Q(baseorder=False),
                Q(symbol__in=symbols),
                join_type="AND",
            ).values()
            campaigns_by_id: dict[str, dict[str, Any]] = {}
            if campaign_ids:
                campaign_rows = await model.SpotCampaigns.filter(
                    campaign_id__in=campaign_ids
                ).values(
                    "campaign_id",
                    "started_at",
                    "sidestep_count",
                    "principal_quote",
                    "cumulative_realized_quote",
                    "cumulative_realized_percent",
                )
                campaigns_by_id = {
                    str(row.get("campaign_id") or "").strip(): row
                    for row in campaign_rows
                    if str(row.get("campaign_id") or "").strip()
                }

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
                campaign = campaigns_by_id.get(str(order.get("campaign_id") or ""))
                order["campaign_started_at"] = (campaign or {}).get(
                    "started_at"
                ) or order.get("open_date")
                order["sidestep_count"] = int(
                    (campaign or {}).get("sidestep_count") or 0
                )
                self._apply_campaign_profit_fields(order, campaign)
            orders.sort(key=self._trade_entry_sort_key)
            return orders
        except BaseORMException as e:
            # Broad catch to keep open trades endpoint responsive.
            logging.error("Error getting open orders. Cause: %s", e)
            return []

    async def get_waiting_trades(self) -> list[dict[str, Any]]:
        """Return active-flat sidestep rows using the shared open-trade shape."""
        return await self.get_open_trades(
            exposure_state=TradeExposureState.FLAT_WAITING_REENTRY.value
        )

    async def get_unsellable_trades(self) -> list[dict[str, Any]]:
        """Return archived unsellable trade remnants."""
        return await self._execute_db(
            model.UnsellableTrades.all().order_by("-id").values(),
            "Error getting unsellable trades from database.",
            [],
        )

    @staticmethod
    def _visible_closed_trades_query():
        """Return the closed-trade query used for terminal user-facing history."""
        return model.ClosedTrades.filter(
            Q(close_reason__isnull=True)
            | ~Q(close_reason__in=NON_TERMINAL_CLOSE_REASON_VALUES)
        )

    async def get_closed_trades(self, page: int = 0) -> list[dict[str, Any]]:
        """Return paginated closed trades."""
        try:
            size = self.CLOSED_TRADES_PAGE_SIZE
            query = self._visible_closed_trades_query().order_by("-id")
            if page == 0:
                orders = await query.limit(size).values()
            else:
                orders = await query.offset(page).limit(size).values()
            return orders
        except BaseORMException as e:
            # Broad catch to keep closed trades endpoint responsive.
            logging.error("Error getting closed orders. Cause: %s", e)
            return []

    async def get_trade_executions(self, deal_id: str) -> list[dict[str, Any]]:
        """Return execution rows for one deal in chronological order."""
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
    ) -> bool:
        """Persist the currently armed proactive TP limit order for a symbol."""
        try:
            updated_count = await model.OpenTrades.filter(symbol=symbol).update(
                tp_limit_order_id=order_id,
                tp_limit_order_price=float(price),
                tp_limit_order_amount=float(amount),
                tp_limit_order_armed_at=datetime.now(timezone.utc).isoformat(),
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

    async def clear_tp_limit_order(self, symbol: str) -> bool:
        """Clear persisted proactive TP limit order metadata for a symbol."""
        updated = await self._write_db(
            model.OpenTrades.filter(symbol=symbol).update(
                tp_limit_order_id=None,
                tp_limit_order_price=None,
                tp_limit_order_amount=None,
                tp_limit_order_armed_at=None,
            ),
            f"Error clearing proactive TP limit order for {symbol}.",
        )
        if updated:
            await self._clear_order_cache()
        return updated

    async def add_partial_sell_execution(
        self,
        symbol: str,
        sold_amount: float,
        sold_proceeds: float,
        sell_executions: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        """Accumulate partial sell totals and append partial sell execution rows."""
        execution_rows = [
            execution
            for execution in (sell_executions or [])
            if isinstance(execution, dict)
        ]

        async def _update_partial_sell_execution() -> None:
            async with in_transaction() as conn:
                open_trade = (
                    await model.OpenTrades.filter(symbol=symbol).using_db(conn).first()
                )
                if open_trade is None:
                    return

                deal_id = open_trade.deal_id or str(uuid4())
                campaign_id = (
                    str(open_trade.campaign_id).strip()
                    if open_trade.campaign_id
                    else None
                )
                history_complete = bool(open_trade.execution_history_complete) and bool(
                    execution_rows
                )
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).update(
                    deal_id=deal_id,
                    execution_history_complete=history_complete,
                    sold_amount=F("sold_amount") + float(sold_amount),
                    sold_proceeds=F("sold_proceeds") + float(sold_proceeds),
                )

                ledger_rows = execution_rows or [
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "role": "partial_sell",
                        "timestamp": "",
                        "price": (
                            float(sold_proceeds) / float(sold_amount)
                            if float(sold_amount) > 0
                            else 0.0
                        ),
                        "amount": float(sold_amount),
                        "ordersize": float(sold_proceeds),
                        "fee": 0.0,
                    }
                ]
                for execution in ledger_rows:
                    if float(execution.get("amount") or 0.0) <= 0:
                        continue
                    await model.TradeExecutions.create(
                        deal_id=deal_id,
                        campaign_id=campaign_id,
                        symbol=str(execution.get("symbol") or symbol),
                        side=str(execution.get("side") or "sell"),
                        role=str(execution.get("role") or "partial_sell"),
                        timestamp=str(execution.get("timestamp") or ""),
                        price=float(execution.get("price") or 0.0),
                        amount=float(execution.get("amount") or 0.0),
                        ordersize=float(execution.get("ordersize") or 0.0),
                        fee=float(execution.get("fee") or 0.0),
                        order_id=(
                            str(execution.get("order_id"))
                            if execution.get("order_id") is not None
                            else None
                        ),
                        order_type=(
                            str(execution.get("order_type"))
                            if execution.get("order_type") is not None
                            else None
                        ),
                        order_count=execution.get("order_count"),
                        so_percentage=(
                            float(execution["so_percentage"])
                            if execution.get("so_percentage") is not None
                            else None
                        ),
                        signal_name=(
                            str(execution.get("signal_name"))
                            if execution.get("signal_name") is not None
                            else None
                        ),
                        strategy_name=(
                            str(execution.get("strategy_name"))
                            if execution.get("strategy_name") is not None
                            else None
                        ),
                        timeframe=(
                            str(execution.get("timeframe"))
                            if execution.get("timeframe") is not None
                            else None
                        ),
                        metadata_json=(
                            str(execution.get("metadata_json"))
                            if execution.get("metadata_json") is not None
                            else None
                        ),
                        using_db=conn,
                    )

        await run_sqlite_write_with_retry(
            _update_partial_sell_execution,
            f"updating partial sell execution for {symbol}",
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
                    await model.TradeExecutions.filter(
                        deal_id=open_trade.deal_id,
                    ).using_db(conn).delete()

        try:
            await run_sqlite_write_with_retry(
                _delete_open_trade,
                f"deleting open trades for {symbol}",
            )
            logging.debug("Deleted open trade for %s.", symbol)
        except BaseORMException as exc:
            self._log_db_error(f"Error deleting open trades for {symbol}.", exc)

    async def create_closed_trades(self, payload: dict[str, Any]) -> None:
        """Create a closed trade entry."""
        await self._write_db(
            model.ClosedTrades.create(**payload),
            "Error creating closed trade.",
        )

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
                        await model.TradeReplayCandles.filter(
                            deal_id=deal_id,
                        ).using_db(conn).delete()
                        await model.TradeExecutions.filter(
                            deal_id=deal_id,
                        ).using_db(conn).delete()
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
        """Return total token amount for a symbol."""
        try:
            result = (
                await model.Trades.filter(symbol=symbol)
                .annotate(total_amount=Sum(F("amount")))
                .values_list("total_amount", flat=True)
            )
            return float(result[0] or 0.0)
        except BaseORMException as e:
            # Broad catch to avoid crashing on database aggregation errors.
            logging.error("Error getting total amount from %s. Cause %s", symbol, e)
            return 0.0

    @helper.async_ttl_cache(maxsize=2048, ttl=2)
    async def get_trades_for_orders(self, symbol: str) -> dict[str, Any] | None:
        """Return aggregated trade data for order processing."""
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
                if open_trade and (
                    str(open_trade.get("exposure_state") or "")
                    == TradeExposureState.FLAT_WAITING_REENTRY.value
                ):
                    return self._build_flat_waiting_trade_data(symbol, open_trade)
                return None
            if not baseorder:
                baseorder = min(trades, key=lambda trade: float(trade["timestamp"]))

            safetyorders_count = len(safetyorders)
            unsellable_state = self._extract_unsellable_state(open_trade)

            # For unsellable remnants, OpenTrades carries the authoritative
            # remaining amount/cost after partial close bookkeeping.
            if unsellable_state["is_unsellable"] and open_trade:
                total_amount = float(open_trade.get("amount") or total_amount)
                total_cost = float(open_trade.get("cost") or total_cost)

            trade_data = {
                "timestamp": latest_order["timestamp"],
                "fee": latest_order["fee"],
                "total_cost": total_cost,
                "total_amount": total_amount,
                "symbol": latest_order["symbol"],
                "deal_id": latest_order.get("deal_id"),
                "campaign_id": (
                    open_trade.get("campaign_id")
                    if open_trade and open_trade.get("campaign_id") is not None
                    else latest_order.get("campaign_id")
                ),
                "lifecycle_mode": (
                    open_trade.get("lifecycle_mode") if open_trade else None
                ),
                "exposure_state": (
                    open_trade.get("exposure_state") if open_trade else None
                ),
                "direction": latest_order["direction"],
                "side": latest_order["side"],
                "bot": latest_order["bot"],
                "bo_price": baseorder["price"],
                "current_price": current_price,
                "safetyorders": safetyorders,
                "safetyorders_count": safetyorders_count,
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
                **unsellable_state,
            }
            return trade_data
        except BaseORMException:
            # Broad catch to return None when trade aggregation fails.
            return None

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
