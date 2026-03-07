"""Trade persistence and retrieval helpers."""

import os
from typing import Any

import helper
import model
from tortoise.exceptions import BaseORMException
from tortoise.expressions import F
from tortoise.functions import Sum
from tortoise.models import Q

logging = helper.LoggerFactory.get_logger("logs/trades.log", "trades")


class Trades:
    """Database access layer for trade entities."""

    CLOSED_TRADES_PAGE_SIZE = max(
        1, int(os.getenv("MOONWALKER_CLOSED_TRADES_PAGE_SIZE", "10"))
    )

    @helper.async_ttl_cache(maxsize=1024, ttl=60)
    async def get_trade_by_ordertype(
        self, symbol: str, baseorder: bool = False
    ) -> list[dict[str, Any]]:
        """
        Gives back the specific trade entries for an
        open order (baseorder or safetyorder)
        """
        # Get baseorders
        if baseorder:
            try:
                trade = await model.Trades.filter(
                    Q(baseorder=True), Q(symbol=symbol), join_type="AND"
                ).values()
            except BaseORMException as e:
                # Broad catch to prevent trade queries from crashing call sites.
                logging.error("Error getting baseorders from database. Cause: %s", e)
        # Get safetyorders
        else:
            try:
                trade = await model.Trades.filter(
                    Q(safetyorder=True),
                    Q(baseorder=False),
                    Q(symbol=symbol),
                    join_type="AND",
                ).values()
            except BaseORMException as e:
                # Broad catch to prevent trade queries from crashing call sites.
                logging.error("Error getting safetyorders from database. Cause: %s", e)

        return trade

    async def get_open_trades_by_symbol(
        self, symbol: str
    ) -> list[dict[str, Any]] | None:
        """Return open trades for a symbol."""
        try:
            open_trades = await model.OpenTrades.filter(symbol=symbol).values()
            return open_trades
        except BaseORMException as e:
            # Broad catch to return partial results when database errors occur.
            logging.error("Error getting open trades from database. Cause: %s", e)

    async def get_trades_by_symbol(self, symbol: str) -> list[dict[str, Any]] | None:
        """Return all trades for a symbol."""
        try:
            trades = await model.Trades.filter(symbol=symbol).values()
            return trades
        except BaseORMException as e:
            # Broad catch to return partial results when database errors occur.
            logging.error("Error getting trades from database. Cause: %s", e)

    async def get_open_trades(self) -> list[dict[str, Any]]:
        """
        Gives back the open orders including all base
        and safetyorders
        """

        try:
            orders = await model.OpenTrades.all().values()
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
            return orders
        except BaseORMException as e:
            # Broad catch to keep open trades endpoint responsive.
            logging.error("Error getting open orders. Cause: %s", e)
            return []

    async def get_closed_trades(self, page: int = 0) -> list[dict[str, Any]]:
        """Return paginated closed trades."""
        try:
            size = self.CLOSED_TRADES_PAGE_SIZE
            if page == 0:
                orders = (
                    await model.ClosedTrades.all().order_by("-id").limit(size).values()
                )
            else:
                orders = (
                    await model.ClosedTrades.all()
                    .order_by("-id")
                    .offset(page)
                    .limit(size)
                    .values()
                )
            return orders
        except BaseORMException as e:
            # Broad catch to keep closed trades endpoint responsive.
            logging.error("Error getting closed orders. Cause: %s", e)
            return []

    async def get_closed_trades_length(self) -> int:
        """Return the total number of closed trades."""
        try:
            order_length = await model.ClosedTrades.all().count()
            return order_length
        except BaseORMException as e:
            # Broad catch to keep count endpoint responsive.
            logging.error("Error getting closed order length. Cause: %s", e)
            return 0

    async def create_open_trades(self, payload: dict[str, Any]) -> None:
        """Create an open trade entry."""
        try:
            await model.OpenTrades.create(**payload)
            logging.debug("Added open trade for %s.", payload["symbol"])
        except BaseORMException as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error("Error creating open trade. Cause %s", e)

    async def update_open_trades(self, payload: dict[str, Any], symbol: str) -> None:
        """Update open trades for a symbol."""
        try:
            if await self.get_open_trades_by_symbol(symbol):
                await model.OpenTrades.update_or_create(
                    defaults=payload,
                    symbol=symbol,
                )
        except BaseORMException as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error("Error updating SO count for %s. Cause %s", symbol, e)

    async def add_partial_sell_execution(
        self, symbol: str, sold_amount: float, sold_proceeds: float
    ) -> None:
        """Accumulate partial sell execution totals on the open trade row."""
        try:
            await model.OpenTrades.filter(symbol=symbol).update(
                sold_amount=F("sold_amount") + float(sold_amount),
                sold_proceeds=F("sold_proceeds") + float(sold_proceeds),
            )
        except BaseORMException as e:
            logging.error(
                "Error updating partial sell execution for %s. Cause %s",
                symbol,
                e,
            )

    async def get_partial_sell_execution(self, symbol: str) -> tuple[float, float]:
        """Return accumulated partial sell totals (amount, proceeds)."""
        try:
            open_trade = await model.OpenTrades.filter(symbol=symbol).first()
            if not open_trade:
                return 0.0, 0.0
            return (
                float(getattr(open_trade, "sold_amount", 0.0) or 0.0),
                float(getattr(open_trade, "sold_proceeds", 0.0) or 0.0),
            )
        except BaseORMException as e:
            logging.error(
                "Error reading partial sell execution for %s. Cause %s",
                symbol,
                e,
            )
            return 0.0, 0.0

    async def create_trades(self, payload: dict[str, Any]) -> None:
        """Create a trade entry."""
        try:
            await model.Trades.create(**payload)
            logging.debug("Added trade for %s.", payload["symbol"])
        except BaseORMException as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error("Error creating trade. Cause %s", e)

    async def delete_open_trades(self, symbol: str) -> None:
        """Delete open trades for a symbol."""
        try:
            await model.OpenTrades.filter(symbol=symbol).delete()
            logging.debug("Deleted open trade for %s.", symbol)
        except BaseORMException as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error("Error deleting open trades for %s. Cause %s", symbol, e)

    async def delete_trades(self, symbol: str) -> None:
        """Delete trades for a symbol."""
        try:
            await model.Trades.filter(symbol=symbol).delete()
            logging.debug("Deleted trade for %s.", symbol)
        except BaseORMException as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error("Error deleting trades for %s. Cause %s", symbol, e)

    async def create_closed_trades(self, payload: dict[str, Any]) -> None:
        """Create a closed trade entry."""
        try:
            await model.ClosedTrades.create(**payload)
        except BaseORMException as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error("Error creating closed trade. Cause %s", e)

    async def delete_closed_trade(self, trade_id: int) -> bool:
        """Delete a closed trade by its identifier."""
        try:
            deleted_count = await model.ClosedTrades.filter(id=trade_id).delete()
            return deleted_count > 0
        except BaseORMException as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error("Error deleting closed trade %s. Cause %s", trade_id, e)
            return False

    async def get_token_amount_from_trades(self, symbol: str) -> float | None:
        """Return total token amount for a symbol."""
        try:
            result = (
                await model.Trades.filter(symbol=symbol)
                .annotate(total_amount=Sum(F("amount")))
                .values_list("total_amount", flat=True)
            )
            return result[0]
        except BaseORMException as e:
            # Broad catch to avoid crashing on database aggregation errors.
            logging.error("Error getting total amount from %s. Cause %s", symbol, e)
            return None

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
                return None
            if not baseorder:
                baseorder = min(trades, key=lambda trade: float(trade["timestamp"]))

            safetyorders_count = len(safetyorders)
            is_unsellable = False
            unsellable_reason = None
            unsellable_amount = 0.0
            unsellable_min_notional = None
            unsellable_estimated_notional = None

            if open_trade:
                unsellable_amount = float(open_trade.get("unsellable_amount") or 0.0)
                unsellable_reason = open_trade.get("unsellable_reason")
                unsellable_min_notional = open_trade.get("unsellable_min_notional")
                unsellable_estimated_notional = open_trade.get(
                    "unsellable_estimated_notional"
                )
                is_unsellable = unsellable_amount > 0 and bool(unsellable_reason)

                # For unsellable remnants, OpenTrades carries the authoritative
                # remaining amount/cost after partial close bookkeeping.
                if is_unsellable:
                    total_amount = float(open_trade.get("amount") or total_amount)
                    total_cost = float(open_trade.get("cost") or total_cost)

            trade_data = {
                "timestamp": latest_order["timestamp"],
                "fee": latest_order["fee"],
                "total_cost": total_cost,
                "total_amount": total_amount,
                "symbol": latest_order["symbol"],
                "direction": latest_order["direction"],
                "side": latest_order["side"],
                "bot": latest_order["bot"],
                "bo_price": baseorder["price"],
                "current_price": current_price,
                "safetyorders": safetyorders,
                "safetyorders_count": safetyorders_count,
                "ordertype": baseorder["ordertype"],
                "is_unsellable": is_unsellable,
                "unsellable_reason": unsellable_reason,
                "unsellable_amount": unsellable_amount,
                "unsellable_min_notional": unsellable_min_notional,
                "unsellable_estimated_notional": unsellable_estimated_notional,
            }

            return trade_data
        except BaseORMException:
            # Broad catch to return None when trade aggregation fails.
            # logging.debug(f"No trade for symbol {symbol} - Cause: {e}")
            return None

    async def get_symbols(self) -> list[str]:
        """Return distinct trade symbols."""
        data = await model.Trades.all().distinct().values_list("symbol", flat=True)
        return data
