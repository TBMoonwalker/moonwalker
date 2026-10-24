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
from service.exchange_types import (
    ExchangeOrderReport,
)
from service.exchange_types import decimal_evidence as exchange_decimal_evidence


def decimal_evidence(value: Any) -> str:
    """Read shared exact execution values with the legacy domain exception."""
    try:
        return exchange_decimal_evidence(value)
    except ValueError as exc:
        raise AccumulationStateError(str(exc)) from exc


class AccumulationFill(ExchangeOrderReport):
    """Compatibility boundary for existing exact inventory/checkpoint consumers."""

    @classmethod
    def from_order(cls, order: dict[str, Any]) -> AccumulationFill:
        """Preserve accumulation's explicit-status requirement and exception type."""
        try:
            if not isinstance(order, dict) or order.get("status") is None:
                raise ValueError("Unknown order status is not fill evidence.")
            return super().from_order(order)
        except ValueError as exc:
            raise AccumulationStateError(str(exc)) from exc

    def serialize(self) -> str:
        """Retain the existing checkpoint shape; raw evidence keeps request data."""
        data = asdict(self)
        data.pop("requested_quantity", None)
        data.pop("order_status", None)
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


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
