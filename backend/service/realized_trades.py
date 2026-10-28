"""Select closed records with trustworthy realized-profit fields."""

import model
from tortoise.expressions import F, Q


def realized_closed_trades():
    """Exclude old manual stops whose profit included an unsold valuation."""
    return model.ClosedTrades.filter(
        Q(close_reason__isnull=True)
        | ~Q(close_reason="manual_stop")
        | Q(valuation_quantity__isnull=False)
    )


def completed_sale_trades():
    """Keep legacy closes while excluding manual stops from outcome learning."""
    return model.ClosedTrades.filter(
        Q(close_reason__isnull=True) | ~Q(close_reason="manual_stop")
    )


async def has_unverified_manual_stop_profit() -> bool:
    """Detect legacy stops and partial sales without complete fee evidence."""
    return (
        await model.ClosedTrades.filter(close_reason="manual_stop")
        .filter(
            Q(valuation_quantity__isnull=True) | Q(amount__gt=F("valuation_quantity"))
        )
        .exists()
    )
