"""Trade persistence and retrieval helpers."""

from typing import Any

import helper
import model
from tortoise.expressions import F
from tortoise.functions import Sum
from tortoise.models import Q

logging = helper.LoggerFactory.get_logger("logs/trades.log", "trades")


class Trades:
    """Database access layer for trade entities."""

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
                    Q(baseorder__gt=0), Q(symbol=symbol), join_type="AND"
                ).values()
            except Exception as e:
                # Broad catch to prevent trade queries from crashing call sites.
                logging.error(f"Error getting baseorders from database. Cause: {e}")
        # Get safetyorders
        else:
            try:
                trade = await model.Trades.filter(
                    Q(safetyorder__gt=0), Q(symbol=symbol), join_type="AND"
                ).values()
            except Exception as e:
                # Broad catch to prevent trade queries from crashing call sites.
                logging.error(f"Error getting safetyorders from database. Cause: {e}")

        return trade

    async def get_open_trades_by_symbol(
        self, symbol: str
    ) -> list[dict[str, Any]] | None:
        """Return open trades for a symbol."""
        try:
            open_trades = await model.OpenTrades.filter(symbol=symbol).values()
            return open_trades
        except Exception as e:
            # Broad catch to return partial results when database errors occur.
            logging.error(f"Error getting open trades from database. Cause: {e}")

    async def get_trades_by_symbol(self, symbol: str) -> list[dict[str, Any]] | None:
        """Return all trades for a symbol."""
        try:
            trades = await model.Trades.filter(symbol=symbol).values()
            return trades
        except Exception as e:
            # Broad catch to return partial results when database errors occur.
            logging.error(f"Error getting trades from database. Cause: {e}")

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
                Q(baseorder__gt=0), Q(symbol__in=symbols), join_type="AND"
            ).values()
            safetyorders = await model.Trades.filter(
                Q(safetyorder__gt=0), Q(symbol__in=symbols), join_type="AND"
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
        except Exception as e:
            # Broad catch to keep open trades endpoint responsive.
            logging.error(f"Error getting open orders. Cause: {e}")
            return []

    async def get_closed_trades(self, page: int = 0) -> list[dict[str, Any]]:
        """Return paginated closed trades."""
        try:
            # TODO: hardcoded to 10 entries per page right now
            size = 10
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
        except Exception as e:
            # Broad catch to keep closed trades endpoint responsive.
            logging.error(f"Error getting closed orders. Cause: {e}")
            return []

    async def get_closed_trades_length(self) -> int:
        """Return the total number of closed trades."""
        try:
            order_length = await model.ClosedTrades.all().count()
            return order_length
        except Exception as e:
            # Broad catch to keep count endpoint responsive.
            logging.error(f"Error getting closed order length. Cause: {e}")
            return 0

    async def create_open_trades(self, payload: dict[str, Any]) -> None:
        """Create an open trade entry."""
        try:
            await model.OpenTrades.create(**payload)
            logging.debug(f"Added open trade for {payload['symbol']}.")
        except Exception as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error(f"Error creating open trade. Cause {e}")

    async def update_open_trades(self, payload: dict[str, Any], symbol: str) -> None:
        """Update open trades for a symbol."""
        try:
            if await self.get_open_trades_by_symbol(symbol):
                await model.OpenTrades.update_or_create(
                    defaults=payload,
                    symbol=symbol,
                )
        except Exception as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error(f"Error updating SO count for {symbol}. Cause {e}")

    async def create_trades(self, payload: dict[str, Any]) -> None:
        """Create a trade entry."""
        try:
            await model.Trades.create(**payload)
            logging.debug(f"Added trade for {payload['symbol']}.")
        except Exception as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error(f"Error creating trade. Cause {e}")

    async def delete_open_trades(self, symbol: str) -> None:
        """Delete open trades for a symbol."""
        try:
            await model.OpenTrades.filter(symbol=symbol).delete()
            logging.debug(f"Deleted open trade for {symbol}.")
        except Exception as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error(f"Error deleting open trades for {symbol}. Cause {e}")

    async def delete_trades(self, symbol: str) -> None:
        """Delete trades for a symbol."""
        try:
            await model.Trades.filter(symbol=symbol).delete()
            logging.debug(f"Deleted trade for {symbol}.")
        except Exception as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error(f"Error deleting trades for {symbol}. Cause {e}")

    async def create_closed_trades(self, payload: dict[str, Any]) -> None:
        """Create a closed trade entry."""
        try:
            await model.ClosedTrades.create(**payload)
        except Exception as e:
            # Broad catch to avoid crashing on database write errors.
            logging.error(f"Error creating closed trade. Cause {e}")

    async def get_token_amount_from_trades(self, symbol: str) -> float | None:
        """Return total token amount for a symbol."""
        try:
            result = (
                await model.Trades.filter(symbol=symbol)
                .annotate(total_amount=Sum(F("amount") + F("amount_fee")))
                .values_list("total_amount", flat=True)
            )
            return result[0]
        except Exception as e:
            # Broad catch to avoid crashing on database aggregation errors.
            logging.error(f"Error getting total amount from {symbol}. Cause {e}")
            return None

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
            if opentrades:
                current_price = opentrades[0]["current_price"]

            for order in trades:
                amount = float(order["amount"])
                amount_fee = float(order["amount_fee"])
                total_cost += float(order["ordersize"])
                total_amount += amount + amount_fee

                # Safetyorder data
                if order["safetyorder"] == 1:
                    safetyorder = {
                        "price": order["price"],
                        "so_percentage": order["so_percentage"],
                        "ordersize": order["ordersize"],
                    }
                    safetyorders.append(safetyorder)

            safetyorders_count = len(safetyorders)

            trade_data = {
                "timestamp": trades[-1]["timestamp"],
                "fee": trades[-1]["fee"],
                "total_cost": total_cost,
                "total_amount": total_amount,
                "symbol": trades[-1]["symbol"],
                "direction": trades[-1]["direction"],
                "side": trades[-1]["side"],
                "bot": trades[-1]["bot"],
                "bo_price": trades[0]["price"],
                "current_price": current_price,
                "safetyorders": safetyorders,
                "safetyorders_count": safetyorders_count,
                "ordertype": trades[0]["ordertype"],
            }

            return trade_data
        except Exception:
            # Broad catch to return None when trade aggregation fails.
            # logging.debug(f"No trade for symbol {symbol} - Cause: {e}")
            return None

    async def get_symbols(self) -> list[str]:
        """Return distinct trade symbols."""
        data = await model.Trades.all().distinct().values_list("symbol", flat=True)
        return data
