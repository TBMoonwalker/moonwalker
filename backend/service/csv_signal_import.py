"""CSV trade import service used by the csv_signal plugin."""

import csv
import io
from collections import defaultdict
from typing import Any

import helper
import model
from service.database import run_sqlite_write_with_retry
from service.trade_math import (
    calculate_order_size,
    calculate_so_percentage,
    count_decimal_places,
    parse_date_to_ms,
)
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger("logs/signal.log", "csv_signal_import")


class CSVSignalImportService:
    """Parse CSV rows and persist imported open trades atomically."""

    async def import_from_csv(
        self,
        csv_content: str,
        quote_currency: str,
        take_profit: float,
        bot_name: str = "csv_signal",
    ) -> dict[str, Any]:
        """Import open trades from CSV.

        CSV format:
            date;symbol;price;amount

        Rules:
            - oldest row per symbol -> base order
            - subsequent rows -> safety orders
            - so_percentage uses price delta vs previous order price
        """
        rows_by_symbol = self._parse_csv_rows(csv_content, quote_currency)
        symbols = sorted(rows_by_symbol.keys())

        open_symbols = await model.OpenTrades.filter(symbol__in=symbols).values_list(
            "symbol", flat=True
        )
        if open_symbols:
            joined = ", ".join(sorted(set(open_symbols)))
            raise ValueError(
                "CSV signal import blocked. Symbols already open: "
                f"{joined}. Close trades before importing."
            )

        existing_trade_symbols = await model.Trades.filter(
            symbol__in=symbols
        ).values_list("symbol", flat=True)
        if existing_trade_symbols:
            joined = ", ".join(sorted(set(existing_trade_symbols)))
            raise ValueError(
                "CSV signal import blocked. Existing trade rows found for symbols: "
                f"{joined}. Clean rows before importing."
            )

        trade_rows: list[model.Trades] = []
        open_trade_payloads: list[dict[str, Any]] = []
        imported_rows = 0
        first_timestamp_by_symbol: dict[str, int] = {}

        for symbol in symbols:
            entries = sorted(rows_by_symbol[symbol], key=lambda row: row["timestamp"])
            if not entries:
                continue

            total_amount = 0.0
            total_cost = 0.0
            first_timestamp = int(entries[0]["timestamp"])
            first_timestamp_by_symbol[symbol] = first_timestamp
            previous_price: float | None = None

            for index, entry in enumerate(entries):
                amount = float(entry["amount"])
                price = float(entry["price"])
                ordersize = calculate_order_size(price=price, amount=amount)
                total_amount += amount
                total_cost += ordersize

                is_base = index == 0
                so_percentage = calculate_so_percentage(
                    price=price,
                    previous_price=previous_price,
                    is_base=is_base,
                )

                previous_price = price
                trade_rows.append(
                    model.Trades(
                        timestamp=str(entry["timestamp"]),
                        ordersize=ordersize,
                        fee=0.0,
                        precision=entry["precision"],
                        amount=amount,
                        amount_fee=0.0,
                        price=price,
                        symbol=symbol,
                        orderid=(
                            f"csv-signal-{symbol.replace('/', '')}-"
                            f"{entry['timestamp']}-{index}"
                        ),
                        bot=bot_name,
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
            tp_price = avg_price * (1 + (take_profit / 100.0)) if take_profit else 0.0
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
                if trade_rows:
                    await model.Trades.bulk_create(trade_rows, using_db=conn)
                for payload in open_trade_payloads:
                    await model.OpenTrades.create(**payload, using_db=conn)

        await run_sqlite_write_with_retry(
            _persist_import, "importing csv signal trades"
        )
        logging.info(
            "Imported CSV signal trades for %s symbols (%s rows).",
            len(symbols),
            imported_rows,
        )
        return {
            "symbols": symbols,
            "symbol_count": len(symbols),
            "row_count": imported_rows,
            "first_timestamp_by_symbol": first_timestamp_by_symbol,
        }

    def _parse_csv_rows(
        self, csv_content: str, quote_currency: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Parse and validate CSV rows grouped by normalized symbol."""
        normalized_content = (csv_content or "").strip()
        if not normalized_content:
            raise ValueError("CSV is empty.")

        csv_reader = csv.reader(io.StringIO(normalized_content), delimiter=";")
        first_row = next(csv_reader, None)
        if first_row is None:
            raise ValueError("CSV is empty.")

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

            timestamp_ms = parse_date_to_ms(date_raw)
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

            symbol = self._normalize_symbol(symbol_raw, quote_currency)
            grouped_rows[symbol].append(
                {
                    "timestamp": timestamp_ms,
                    "price": price,
                    "amount": amount,
                    "precision": count_decimal_places(amount_raw),
                }
            )

        if not grouped_rows:
            raise ValueError("CSV does not contain importable rows.")

        return grouped_rows

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

    # Compatibility aliases for existing call sites/tests.
    def _parse_date_to_ms(self, value: str) -> int | None:
        return parse_date_to_ms(value)

    def _count_decimal_places(self, value: str) -> int:
        return count_decimal_places(value)
