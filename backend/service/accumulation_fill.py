"""Exact cumulative fill evidence and bounded inventory arithmetic.

Exchange adapters provide cumulative order totals, never per-trade deltas mixed
with order totals. Missing fees remain unknown until explicit evidence arrives.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Any

from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.order_requests import normalize_order_symbol

TERMINAL_ORDER_STATUSES = frozenset(
    {"closed", "filled", "canceled", "cancelled", "expired", "rejected"}
)


def decimal_evidence(value: Any) -> str:
    """Preserve a reported number's decimal spelling; reject absent/invalid data."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise AccumulationStateError("Missing or invalid decimal evidence.")
    return canonical_decimal(str(value))


@dataclass(frozen=True)
class AccumulationFill:
    """Validated cumulative order report from a trusted exchange lookup adapter."""

    order_id: str
    symbol: str
    side: str
    filled: str
    quote_cost: str
    fees: dict[str, str]
    fees_complete: bool
    terminal: bool
    timestamp_ms: int

    @classmethod
    def from_order(cls, order: dict[str, Any]) -> AccumulationFill:
        """Read raw CCXT order totals without guessing missing fees or cost."""
        if not isinstance(order, dict):
            raise AccumulationStateError("An order evidence object is required.")
        order_id = order.get("id")
        if not isinstance(order_id, str) or not order_id or len(order_id) > 128:
            raise AccumulationStateError("An exchange order identity is required.")
        symbol = order.get("symbol")
        if not isinstance(symbol, str) or len(symbol.split("/")) != 2 or ":" in symbol:
            raise AccumulationStateError("A spot symbol is required.")
        side = order.get("side")
        if not isinstance(side, str) or side not in {"buy", "sell"}:
            raise AccumulationStateError("An explicit fill side is required.")
        status = order.get("status")
        if not isinstance(status, str) or status not in TERMINAL_ORDER_STATUSES | {
            "open"
        }:
            raise AccumulationStateError("Unknown order status is not fill evidence.")
        filled, cost = (
            decimal_evidence(order.get("filled")),
            decimal_evidence(order.get("cost")),
        )
        if (Decimal(filled) > 0) != (Decimal(cost) > 0):
            raise AccumulationStateError("Filled quantity and cost must agree.")
        if status in {"closed", "filled"} and Decimal(filled) == 0:
            raise AccumulationStateError("A closed order needs positive fill evidence.")
        timestamp = order.get("lastTradeTimestamp") or order.get("timestamp")
        if type(timestamp) is not int or not 0 <= timestamp < 2**63:
            raise AccumulationStateError("A valid execution timestamp is required.")
        raw_fees = order.get("fees")
        if not raw_fees:
            raw_fees = [order["fee"]] if order.get("fee") else []
        if not isinstance(raw_fees, list) or len(raw_fees) > 32:
            raise AccumulationStateError("Invalid or oversized fee evidence.")
        fees: dict[str, str] = {}
        with localcontext() as context:
            context.prec = 512
            for fee in raw_fees:
                if not isinstance(fee, dict):
                    raise AccumulationStateError("Invalid fee evidence.")
                currency = fee.get("currency")
                if not isinstance(currency, str) or not currency or len(currency) > 32:
                    raise AccumulationStateError("Fee currency is required.")
                currency = currency.upper()
                value = Decimal(decimal_evidence(fee.get("cost")))
                fees[currency] = format(Decimal(fees.get(currency, "0")) + value, "f")
        if Decimal(filled) == 0 and any(Decimal(value) for value in fees.values()):
            raise AccumulationStateError("Zero-fill fees require explicit repair.")
        return cls(
            order_id,
            normalize_order_symbol(symbol),
            side,
            filled,
            cost,
            fees,
            bool(raw_fees) or Decimal(filled) == 0,
            status in TERMINAL_ORDER_STATUSES,
            timestamp,
        )

    def serialize(self) -> str:
        """Return a stable checkpoint representation."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class AccumulationInventory:
    """Exact remaining inventory; unknown basis is never replaced with zero."""

    quantity: str
    remaining_cost: str | None
    contributed_quote: str | None
    disposal_proceeds: str
    fees: dict[str, str]
    pending_fee_reports: int = 0
    basis_provenance: str = "exchange_fills"

    def serialize(self) -> str:
        """Keep exact terminal totals after the live holding is removed."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def apply_fill_delta(
    inventory: AccumulationInventory,
    report: AccumulationFill,
    *,
    previous_filled: str = "0",
    previous_cost: str = "0",
    previous_fees: dict[str, str] | None = None,
    previously_incomplete: bool = False,
) -> tuple[AccumulationInventory, dict[str, Any]]:
    """Apply monotonic cumulative deltas and proportional weighted-average basis."""
    with localcontext() as context:
        # Bounded inputs have at most 256 integer/fraction digits combined.
        # Extra precision also keeps proportional cost allocation deterministic.
        context.prec = 512
        previous_fees = previous_fees or {}
        amount = Decimal(report.filled) - Decimal(previous_filled)
        cost = Decimal(report.quote_cost) - Decimal(previous_cost)
        fees = {
            currency: Decimal(report.fees.get(currency, "0")) - Decimal(value)
            for currency, value in {
                **{key: "0" for key in report.fees},
                **previous_fees,
            }.items()
        }
        if amount < 0 or cost < 0 or any(value < 0 for value in fees.values()):
            raise AccumulationStateError("Cumulative fill or fees moved backward.")
        if (amount > 0) != (cost > 0):
            raise AccumulationStateError(
                "Incremental fill and cost evidence do not agree."
            )
        base, quote = report.symbol.split("/")
        base_fee, quote_fee = fees.get(base, Decimal(0)), fees.get(quote, Decimal(0))
        quantity = Decimal(inventory.quantity)
        basis = (
            Decimal(inventory.remaining_cost)
            if inventory.remaining_cost is not None
            else None
        )
        contributed = (
            Decimal(inventory.contributed_quote)
            if inventory.contributed_quote is not None
            else None
        )
        proceeds = Decimal(inventory.disposal_proceeds)
        allocated = None
        if report.side == "buy":
            quantity += amount - base_fee
            basis = basis + cost + quote_fee if basis is not None else None
            contributed = contributed + cost if contributed is not None else None
        else:
            removed = amount + base_fee
            if removed > quantity:
                raise AccumulationStateError(
                    "Sell exceeds owned accumulation inventory."
                )
            allocated = (
                (basis if removed == quantity else basis * removed / quantity)
                if basis is not None and quantity > 0
                else None
            )
            if allocated is not None and removed != quantity:
                allocated = allocated.quantize(Decimal("1e-36"), rounding=ROUND_DOWN)
            basis = basis - allocated if allocated is not None else basis
            quantity -= removed
            proceeds += cost - quote_fee
        if quantity < 0 or proceeds < 0:
            raise AccumulationStateError(
                "Fill would create negative inventory or proceeds."
            )
        totals = dict(inventory.fees)
        for currency, value in fees.items():
            totals[currency] = format(Decimal(totals.get(currency, "0")) + value, "f")
        if len(totals) > 32:
            raise AccumulationStateError("Too many inventory fee currencies.")
        provenance = inventory.basis_provenance
        if any(
            value > 0
            for currency, value in fees.items()
            if currency not in {base, quote}
        ):
            provenance = "unvalued_external_fees" if basis is not None else "unknown"
        pending = (
            inventory.pending_fee_reports
            - int(previously_incomplete)
            + int(not report.fees_complete and Decimal(report.filled) > 0)
        )
        result = AccumulationInventory(
            format(quantity, "f"),
            format(basis, "f") if basis is not None else None,
            format(contributed, "f") if contributed is not None else None,
            format(proceeds, "f"),
            totals,
            pending,
            provenance,
        )
        for value in (
            result.quantity,
            result.remaining_cost,
            result.contributed_quote,
            result.disposal_proceeds,
            *result.fees.values(),
        ):
            if value is not None:
                canonical_decimal(value)
        return result, {
            "filled": format(amount, "f"),
            "quote_cost": format(cost, "f"),
            "fees": {key: format(value, "f") for key, value in fees.items()},
            "allocated_basis": format(allocated, "f")
            if allocated is not None
            else None,
        }
