"""Trade persistence and retrieval helpers."""

import csv
import io
import os
from collections import defaultdict
from datetime import datetime
from typing import Any

import helper
import model
from service.database import run_sqlite_write_with_retry
from tortoise.exceptions import BaseORMException
from tortoise.expressions import F
from tortoise.functions import Sum
from tortoise.models import Q
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger("logs/trades.log", "trades")


class Trades:
    """Database access layer for trade entities."""

    CLOSED_TRADES_PAGE_SIZE = max(
        1, int(os.getenv("MOONWALKER_CLOSED_TRADES_PAGE_SIZE", "10"))
    )

    _DATE_FORMATS = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
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

    async def import_open_trades_from_csv(
        self,
        csv_content: str,
        quote_currency: str,
        take_profit: float,
        first_so_deviation: float,
        safety_step_scale: float,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Import open trades from CSV.

        Args:
            csv_content: Raw CSV data with `;` as delimiter.
            quote_currency: Running bot quote currency.
            take_profit: Configured take-profit percentage.
            overwrite: Whether existing symbols should be replaced.

        Returns:
            Summary dictionary for imported rows and symbols.
        """
        rows_by_symbol = self._parse_csv_rows(csv_content, quote_currency)
        symbols = sorted(rows_by_symbol.keys())

        if not overwrite:
            open_symbols = await model.OpenTrades.filter(
                symbol__in=symbols
            ).values_list("symbol", flat=True)
            trade_symbols = await model.Trades.filter(symbol__in=symbols).values_list(
                "symbol", flat=True
            )
            existing_symbols = sorted(set(open_symbols) | set(trade_symbols))
            if existing_symbols:
                joined = ", ".join(existing_symbols)
                raise ValueError(
                    "Import blocked. Existing symbols found: "
                    f"{joined}. Enable overwrite to replace them."
                )

        trade_rows: list[model.Trades] = []
        open_trade_payloads: list[dict[str, Any]] = []
        imported_rows = 0

        for symbol in symbols:
            entries = sorted(rows_by_symbol[symbol], key=lambda row: row["timestamp"])
            if not entries:
                continue

            first_timestamp = int(entries[0]["timestamp"])
            total_amount = 0.0
            total_cost = 0.0
            base_price = float(entries[0]["price"])
            imported_so_percentages: list[float] = []

            for index, entry in enumerate(entries):
                amount = float(entry["amount"])
                price = float(entry["price"])
                ordersize = price * amount
                total_amount += amount
                total_cost += ordersize
                is_base = index == 0
                so_percentage = 0.0
                if not is_base and base_price > 0:
                    so_percentage = self._derive_import_so_percentage(
                        so_index=index,
                        imported_so_percentages=imported_so_percentages,
                        first_so_deviation=first_so_deviation,
                        safety_step_scale=safety_step_scale,
                        base_price=base_price,
                        entry_price=price,
                    )
                    imported_so_percentages.append(so_percentage)

                trade_rows.append(
                    model.Trades(
                        timestamp=str(entry["timestamp"]),
                        ordersize=ordersize,
                        fee=0.0,
                        precision=entry["precision"],
                        amount=amount,
                        amount_fee=amount,
                        price=price,
                        symbol=symbol,
                        orderid=(
                            f"manual-import-{symbol.replace('/', '')}-"
                            f"{entry['timestamp']}-{index}"
                        ),
                        bot="manual-import",
                        ordertype="market",
                        baseorder=is_base,
                        safetyorder=not is_base,
                        order_count=index,
                        so_percentage=so_percentage,
                        direction="long",
                        side="buy",
                    )
                )
                imported_rows += 1

            avg_price = total_cost / total_amount if total_amount > 0 else 0.0
            tp_price = avg_price * (1 + (take_profit / 100)) if take_profit else 0.0
            open_trade_payloads.append(
                {
                    "symbol": symbol,
                    "so_count": max(0, len(entries) - 1),
                    "profit": 0.0,
                    "profit_percent": 0.0,
                    "amount": total_amount,
                    "cost": total_cost,
                    "current_price": 0.0,
                    "tp_price": tp_price,
                    "avg_price": avg_price,
                    "open_date": str(first_timestamp),
                }
            )

        async def _persist_import() -> None:
            async with in_transaction() as conn:
                if overwrite:
                    await model.Trades.filter(symbol__in=symbols).using_db(
                        conn
                    ).delete()
                    await model.OpenTrades.filter(symbol__in=symbols).using_db(
                        conn
                    ).delete()

                if trade_rows:
                    await model.Trades.bulk_create(trade_rows, using_db=conn)

                for payload in open_trade_payloads:
                    await model.OpenTrades.create(**payload, using_db=conn)

        await run_sqlite_write_with_retry(_persist_import, "importing open trades csv")

        return {
            "symbols": symbols,
            "symbol_count": len(symbols),
            "row_count": imported_rows,
            "fee_currency": quote_currency,
            "overwrite": overwrite,
        }

    def _parse_csv_rows(
        self, csv_content: str, quote_currency: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Parse and validate CSV rows grouped by symbol."""
        normalized_content = (csv_content or "").strip()
        if not normalized_content:
            raise ValueError("CSV is empty.")

        csv_reader = csv.reader(io.StringIO(normalized_content), delimiter=";")
        first_row = next(csv_reader, None)
        if first_row is None:
            raise ValueError("CSV header is missing.")
        expected_header = ["date", "symbol", "price", "amount"]
        normalized_first_row = [column.strip().lower() for column in first_row]
        has_header = normalized_first_row == expected_header

        rows_to_process: list[tuple[int, list[str]]] = []
        if has_header:
            start_line = 2
        else:
            start_line = 1
            rows_to_process.append((1, first_row))

        grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        rows_to_process.extend(
            (line_number, row)
            for line_number, row in enumerate(csv_reader, start=start_line + 1)
        )

        for line_number, row in rows_to_process:
            if not row or all(not str(cell).strip() for cell in row):
                continue
            if len(row) != 4:
                raise ValueError(
                    f"Invalid CSV at line {line_number}. Expected 4 columns."
                )

            date_raw = row[0].strip()
            symbol_raw = row[1].strip()
            price_raw = row[2].strip().replace(",", ".")
            amount_raw = row[3].strip().replace(",", ".")
            if not date_raw or not symbol_raw or not price_raw or not amount_raw:
                raise ValueError(
                    f"Invalid CSV at line {line_number}. Empty value detected."
                )

            timestamp_ms = self._parse_date_to_ms(date_raw)
            if timestamp_ms is None:
                raise ValueError(f"Invalid date at line {line_number}: '{date_raw}'.")

            try:
                price = float(price_raw)
                amount = float(amount_raw)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid numeric value at line {line_number}."
                ) from exc

            if price <= 0 or amount <= 0:
                raise ValueError(
                    f"Invalid CSV at line {line_number}. Price and amount must be > 0."
                )

            precision = self._count_decimal_places(price_raw)
            symbol = self._normalize_symbol(symbol_raw, quote_currency)
            grouped_rows[symbol].append(
                {
                    "timestamp": timestamp_ms,
                    "price": price,
                    "amount": amount,
                    "precision": precision,
                }
            )

        if not grouped_rows:
            raise ValueError("CSV does not contain importable rows.")

        return grouped_rows

    def _derive_import_so_percentage(
        self,
        so_index: int,
        imported_so_percentages: list[float],
        first_so_deviation: float,
        safety_step_scale: float,
        base_price: float,
        entry_price: float,
    ) -> float:
        """Derive safety-order percentage aligned with DCA progression.

        If DCA config values are unavailable, fall back to the imported entry drawdown
        versus base order price.
        """
        if first_so_deviation > 0 and safety_step_scale > 0:
            # DCA persists SO percentage as step increment per order.
            # so_index=1 => first safety order increment, so_index=2 => second increment...
            incremental = abs(first_so_deviation) * (
                safety_step_scale ** (so_index - 1)
            )
            return round(incremental, 2)

        # Fallback for incomplete DCA config.
        return abs(round(((entry_price - base_price) / base_price) * 100, 2))

    def _normalize_symbol(self, symbol_raw: str, quote_currency: str) -> str:
        """Normalize symbol to `BASE/QUOTE` format."""
        symbol = symbol_raw.strip().upper().replace(" ", "")
        symbol = symbol.replace("_", "/")
        if "-" in symbol and "/" not in symbol:
            symbol = symbol.replace("-", "/")

        if "/" in symbol:
            parts = symbol.split("/")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValueError(f"Invalid symbol '{symbol_raw}'.")
            base, quote = parts[0], parts[1]
            return f"{base}/{quote}"

        if quote_currency and symbol.endswith(quote_currency):
            base = symbol[: -len(quote_currency)]
            if base:
                return f"{base}/{quote_currency}"

        if "/" not in symbol and "-" not in symbol:
            return f"{symbol}/{quote_currency}"

        raise ValueError(
            f"Invalid symbol '{symbol_raw}'. Use BASE/QUOTE or BASE-{quote_currency}."
        )

    def _parse_date_to_ms(self, value: str) -> int | None:
        """Parse date-like values to Unix milliseconds."""
        normalized_value = value.strip()
        if not normalized_value:
            return None

        if normalized_value.isdigit():
            numeric = int(normalized_value)
            if numeric > 10_000_000_000:
                return numeric
            return numeric * 1000

        iso_value = normalized_value.replace("Z", "+00:00")
        try:
            iso_dt = datetime.fromisoformat(iso_value)
            return int(iso_dt.timestamp() * 1000)
        except ValueError:
            pass

        for date_format in self._DATE_FORMATS:
            try:
                parsed = datetime.strptime(normalized_value, date_format)
                return int(parsed.timestamp() * 1000)
            except ValueError:
                continue

        return None

    def _count_decimal_places(self, value: str) -> int:
        """Count decimal places for a numeric string."""
        if "." not in value:
            return 0
        return len(value.split(".", maxsplit=1)[1].rstrip("0"))
