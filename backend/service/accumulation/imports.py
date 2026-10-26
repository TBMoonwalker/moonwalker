"""Exact CSV inventory declarations with explicit fee and quantity semantics."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext
from typing import Any

from service.accumulation.contracts import AccumulationStateError, canonical_decimal
from service.accumulation.fill import AccumulationInventory
from service.trade_math import parse_date_to_ms

CSV_RETURN_BASIS = "csv_declared_fees"
RETURN_BASES = frozenset({"exchange_fills", CSV_RETURN_BASIS})
CSV_HEADER = ["date", "symbol", "price", "amount"]
CSV_FEE_HEADER = CSV_HEADER + ["fee", "fee_currency", "amount_type", "fee_quote_value"]


def normalize_csv_symbol(value: str, quote: str) -> str:
    """Normalize the existing CSV symbol spellings without guessing a conversion."""
    symbol = value.strip().upper().replace(" ", "").replace("_", "/")
    if "/" not in symbol:
        symbol = symbol.replace("-", "/")
    if "/" not in symbol:
        symbol = (
            f"{symbol[: -len(quote)]}/{quote}"
            if quote and symbol.endswith(quote)
            else f"{symbol}/{quote}"
        )
    parts = symbol.split("/")
    if len(parts) != 2 or not all(parts):
        raise AccumulationStateError("Invalid CSV symbol; use BASE/QUOTE.")
    return symbol


@dataclass(frozen=True)
class AccumulationImport:
    """Auditable purchase rows; legacy rows retain their original serialized shape."""

    symbol: str
    entries: tuple[tuple[Any, ...], ...]
    quantity: str
    cost: str

    def to_dict(self) -> dict[str, Any]:
        """Persist the complete declaration as part of activation retry identity."""
        return asdict(self)

    def inventory(self) -> AccumulationInventory:
        """Return net inventory and fee-inclusive basis, never subtracting net fees twice."""
        with localcontext() as context:
            context.prec = 512
            base, quote = self.symbol.split("/")
            quantity = Decimal(0)
            principal = Decimal(0)
            basis = Decimal(0)
            fees: dict[str, Decimal] = {}
            missing = 0
            unvalued = False
            for entry in self.entries:
                _, price, amount, *extra = entry
                price, amount = Decimal(price), Decimal(amount)
                fee = Decimal(extra[0]) if extra and extra[0] is not None else None
                currency, mode, value = extra[1:] if extra else (None, "net", None)
                if fee is None:
                    missing += 1
                gross = (
                    amount + (fee or 0)
                    if mode == "net" and currency == base
                    else amount
                )
                net = gross - (fee or 0) if currency == base else amount
                if net <= 0:
                    raise AccumulationStateError(
                        "CSV base fee must leave positive owned coins."
                    )
                quantity += net
                principal += gross * price
                basis += gross * price
                if fee is not None:
                    fees[currency] = fees.get(currency, Decimal(0)) + fee
                    if currency == quote:
                        basis += fee
                    elif currency != base and fee:
                        if value is None:
                            unvalued = True
                        else:
                            basis += Decimal(value)
            if len(fees) > 32:
                raise AccumulationStateError("CSV has too many fee currencies.")
            return AccumulationInventory(
                canonical_decimal(str(quantity), positive=True),
                canonical_decimal(str(basis), positive=True),
                canonical_decimal(str(principal), positive=True),
                "0",
                {key: canonical_decimal(str(value)) for key, value in fees.items()},
                missing,
                "unvalued_external_fees"
                if unvalued
                else "csv_declared_fees_unknown"
                if missing
                else CSV_RETURN_BASIS,
            )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AccumulationImport:
        """Revalidate persisted rows and totals rather than trusting stored summaries."""
        if set(value) != {"symbol", "entries", "quantity", "cost"}:
            raise AccumulationStateError("Incomplete CSV inventory declaration.")
        result = _declaration(value["symbol"], value["entries"])
        if result.quantity != value["quantity"] or result.cost != value["cost"]:
            raise AccumulationStateError("CSV inventory totals disagree with its rows.")
        return result


def _declaration(symbol: str, entries: Any) -> AccumulationImport:
    if not isinstance(symbol, str) or len(symbol.split("/")) != 2:
        raise AccumulationStateError("Invalid CSV inventory symbol.")
    if not isinstance(entries, (list, tuple)) or not 0 < len(entries) <= 10000:
        raise AccumulationStateError("CSV requires between 1 and 10000 rows.")
    normalized = []
    identities = set()
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or len(entry) not in {3, 7}:
            raise AccumulationStateError("Invalid CSV inventory row.")
        timestamp, price, amount, *extra = entry
        if type(timestamp) is not int or not 0 < timestamp < 2**63:
            raise AccumulationStateError("Invalid CSV purchase date.")
        price = canonical_decimal(price, positive=True)
        amount = canonical_decimal(amount, positive=True)
        identity = (timestamp, price, amount)
        if identity in identities:
            raise AccumulationStateError(
                "Duplicate CSV purchase rows require correction."
            )
        identities.add(identity)
        if extra:
            fee, currency, mode, value = extra
            if not isinstance(mode, str) or mode not in {"net", "gross"}:
                raise AccumulationStateError("CSV amount_type must be net or gross.")
            if fee is None:
                if mode == "gross":
                    raise AccumulationStateError(
                        "CSV gross amounts require an explicit fee."
                    )
                if currency is not None or value is not None:
                    raise AccumulationStateError(
                        "CSV fee amount is required with fee currency or value."
                    )
            else:
                fee = canonical_decimal(fee)
                if not isinstance(currency, str) or not re.fullmatch(
                    r"[A-Z0-9][A-Z0-9._-]{0,31}", currency
                ):
                    raise AccumulationStateError(
                        "CSV fee_currency is required for a declared fee."
                    )
                if value is not None:
                    value = canonical_decimal(value)
                    base, quote = symbol.split("/")
                    with localcontext() as context:
                        context.prec = 512
                        expected = (
                            Decimal(fee) * Decimal(price)
                            if currency == base
                            else Decimal(fee)
                        )
                    if (
                        Decimal(fee) == 0
                        and Decimal(value) != 0
                        or currency in {base, quote}
                        and Decimal(value) != expected
                        or Decimal(fee) > 0
                        and Decimal(value) <= 0
                    ):
                        raise AccumulationStateError(
                            "CSV fee quote value disagrees with the declared fee."
                        )
            normalized.append((timestamp, price, amount, fee, currency, mode, value))
        else:
            normalized.append(identity)
    # Sort only by the original purchase identity; optional fields can contain None.
    normalized.sort(key=lambda row: row[:3])
    provisional = AccumulationImport(symbol, tuple(normalized), "0", "0")
    inventory = provisional.inventory()
    assert inventory.remaining_cost is not None
    return AccumulationImport(
        symbol, tuple(normalized), inventory.quantity, inventory.remaining_cost
    )


def parse_accumulation_csv(
    content: str, quote_currency: str, *, now_ms: int
) -> tuple[AccumulationImport, ...]:
    """Read legacy four columns or fee, currency, optional amount_type and quote value."""
    if not isinstance(content, str) or not content.strip() or len(content) > 1_000_000:
        raise AccumulationStateError("CSV must be nonempty and at most 1 MB of text.")
    quote_currency = quote_currency.upper().strip()
    reader = csv.reader(io.StringIO(content.strip().lstrip("\ufeff")), delimiter=";")
    grouped: dict[str, list[tuple[Any, ...]]] = {}
    count = 0
    for line, row in enumerate(reader, start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        if (
            line == 1
            and len(row) in {4, 6, 7, 8}
            and [cell.strip().lower() for cell in row] == CSV_FEE_HEADER[: len(row)]
        ):
            continue
        if len(row) not in {4, 6, 7, 8}:
            raise AccumulationStateError(
                f"CSV line {line} requires 4, 6, 7 or 8 columns."
            )
        timestamp = parse_date_to_ms(row[0].strip())
        if timestamp is None or not 0 < timestamp <= now_ms:
            raise AccumulationStateError(
                f"CSV line {line} requires a past purchase date."
            )
        symbol = normalize_csv_symbol(row[1], quote_currency)
        if symbol.split("/")[-1] != quote_currency or ":" in symbol:
            raise AccumulationStateError(
                "CSV symbol must use the configured spot quote."
            )
        entry: tuple[Any, ...] = (
            timestamp,
            row[2].strip().replace(",", "."),
            row[3].strip().replace(",", "."),
        )
        if len(row) >= 6:
            fee = row[4].strip().replace(",", ".") or None
            currency = row[5].strip().upper() or (
                quote_currency
                if fee is not None and canonical_decimal(fee) == "0"
                else None
            )
            mode = row[6].strip().lower() if len(row) >= 7 and row[6].strip() else "net"
            value = row[7].strip().replace(",", ".") or None if len(row) == 8 else None
            entry += (fee, currency, mode, value)
        grouped.setdefault(symbol, []).append(entry)
        count += 1
        if count > 10000:
            raise AccumulationStateError("CSV exceeds 10000 purchase rows.")
    if not grouped:
        raise AccumulationStateError("CSV does not contain inventory rows.")
    return tuple(_declaration(symbol, grouped[symbol]) for symbol in sorted(grouped))
