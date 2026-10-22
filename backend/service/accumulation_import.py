"""Exact, auditable CSV inventory declarations; these are not exchange fills."""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext
from typing import Any

from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.csv_signal_import import CSVSignalImportService
from service.trade_math import parse_date_to_ms


@dataclass(frozen=True)
class AccumulationImport:
    """Declared net owned quantity and fee-exclusive acquisition cost."""

    symbol: str
    entries: tuple[tuple[int, str, str], ...]
    quantity: str
    cost: str

    def to_dict(self) -> dict[str, Any]:
        """Persist the complete declaration as part of activation retry identity."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AccumulationImport:
        """Revalidate a persisted declaration instead of trusting stored totals."""
        if set(value) != {"symbol", "entries", "quantity", "cost"}:
            raise AccumulationStateError("Incomplete CSV inventory declaration.")
        result = _declaration(value["symbol"], value["entries"])
        if result.quantity != value["quantity"] or result.cost != value["cost"]:
            raise AccumulationStateError("CSV inventory totals disagree with its rows.")
        return result


def _declaration(symbol: str, entries: Any) -> AccumulationImport:
    if not isinstance(entries, (list, tuple)) or not 0 < len(entries) <= 10000:
        raise AccumulationStateError("CSV requires between 1 and 10000 rows.")
    normalized = []
    with localcontext() as context:
        context.prec = 512
        quantity = Decimal(0)
        cost = Decimal(0)
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 3:
                raise AccumulationStateError("Invalid CSV inventory row.")
            timestamp, price, amount = entry
            if type(timestamp) is not int or not 0 < timestamp < 2**63:
                raise AccumulationStateError("Invalid CSV purchase date.")
            price = canonical_decimal(price, positive=True)
            amount = canonical_decimal(amount, positive=True)
            normalized.append((timestamp, price, amount))
            quantity += Decimal(amount)
            cost += Decimal(price) * Decimal(amount)
        if len(set(normalized)) != len(normalized):
            raise AccumulationStateError(
                "Duplicate CSV purchase rows require correction."
            )
        return AccumulationImport(
            symbol,
            tuple(sorted(normalized)),
            canonical_decimal(str(quantity), positive=True),
            canonical_decimal(str(cost), positive=True),
        )


def parse_accumulation_csv(
    content: str, quote_currency: str, *, now_ms: int
) -> tuple[AccumulationImport, ...]:
    """Parse the existing date;symbol;price;amount format without float rounding."""
    if not isinstance(content, str) or not content.strip() or len(content) > 1_000_000:
        raise AccumulationStateError("CSV must be nonempty and at most 1 MB of text.")
    reader = csv.reader(io.StringIO(content.strip().lstrip("\ufeff")), delimiter=";")
    grouped: dict[str, list[tuple[int, str, str]]] = {}
    count = 0
    normalizer = CSVSignalImportService()
    for line, row in enumerate(reader, start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        if line == 1 and [cell.strip().lower() for cell in row] == [
            "date",
            "symbol",
            "price",
            "amount",
        ]:
            continue
        if len(row) != 4:
            raise AccumulationStateError(f"CSV line {line} requires four columns.")
        timestamp = parse_date_to_ms(row[0].strip())
        if timestamp is None or not 0 < timestamp <= now_ms:
            raise AccumulationStateError(
                f"CSV line {line} requires a past purchase date."
            )
        symbol = normalizer._normalize_symbol(row[1], quote_currency)
        if symbol.split("/")[-1] != quote_currency or ":" in symbol:
            raise AccumulationStateError(
                "CSV symbol must use the configured spot quote."
            )
        grouped.setdefault(symbol, []).append(
            (
                timestamp,
                row[2].strip().replace(",", "."),
                row[3].strip().replace(",", "."),
            )
        )
        count += 1
        if count > 10000:
            raise AccumulationStateError("CSV exceeds 10000 purchase rows.")
    if not grouped:
        raise AccumulationStateError("CSV does not contain inventory rows.")
    return tuple(_declaration(symbol, grouped[symbol]) for symbol in sorted(grouped))
