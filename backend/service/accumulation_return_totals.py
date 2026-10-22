"""Bounded routine return accounting; historical rebuilds are maintenance work."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, localcontext
from typing import Any

import model
from service.accumulation_contracts import canonical_decimal


async def record_return_delta(
    activation: Any,
    inventory: Any,
    delta: dict[str, Any],
    *,
    side: str,
    timestamp_ms: int,
    connection: Any,
) -> None:
    """Update derived totals in the caller's fill transaction, exactly once."""
    totals = await model.AccumulationReturnTotals.get_or_none(
        activation=activation
    ).using_db(connection)
    if totals is None:
        if (
            await model.AccumulationFillCheckpoint.filter(activation=activation)
            .using_db(connection)
            .exists()
        ):
            return  # Portable/older history requires one maintenance rebuild first.
        totals = await model.AccumulationReturnTotals.create(
            using_db=connection, activation=activation
        )
    totals.provenance_complete &= inventory.basis_provenance == "exchange_fills"
    totals.last_quantity, totals.last_cost = (
        inventory.quantity,
        inventory.remaining_cost,
    )
    if side == "sell":
        if delta["allocated_basis"] is None:
            totals.provenance_complete = False
        else:
            with localcontext() as context:
                context.prec = 512
                quote = activation.symbol.split("/")[1]
                profit = (
                    Decimal(canonical_decimal(delta["quote_cost"]))
                    - Decimal(canonical_decimal(delta["fees"].get(quote, "0")))
                    - Decimal(canonical_decimal(delta["allocated_basis"]))
                )
                totals.realized_quote = format(
                    Decimal(totals.realized_quote) + profit, "f"
                )
                try:
                    date = (
                        datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc)
                        .date()
                        .isoformat()
                    )
                except (ValueError, OverflowError, OSError):
                    totals.history_complete = False
                else:
                    day, _ = await model.AccumulationReturnDay.get_or_create(
                        activation=activation, date=date, using_db=connection
                    )
                    day.profit = format(Decimal(day.profit) + profit, "f")
                    await day.save(using_db=connection)
    await totals.save(using_db=connection)
