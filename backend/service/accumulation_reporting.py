"""Exact read-only inventory summaries and durable cumulative order history.

These projections do not value coins at a guessed price or infer investment
returns from a legacy float mirror. Order checkpoints remain after full close.
"""

from __future__ import annotations

import json
from decimal import Decimal, localcontext
from typing import Any

import model
from service.accumulation_contracts import canonical_decimal
from tortoise.backends.base.client import BaseDBAsyncClient


def _amount(value: Any) -> str | None:
    try:
        return canonical_decimal(value)
    except (ValueError, TypeError):
        return None


def _fees(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict) or len(value) > 32:
        return None
    result = {}
    for currency, amount in value.items():
        if not isinstance(currency, str) or not currency or len(currency) > 32:
            return None
        parsed = _amount(amount)
        if parsed is None:
            return None
        result[currency] = parsed
    return result


def _inventory(value: str | None) -> dict[str, Any] | None:
    try:
        raw = json.loads(value or "null")
        if not isinstance(raw, dict):
            return None
        pending = raw.get("pending_fee_reports")
        if type(pending) is not int or pending < 0:
            return None
        return {
            "net_quantity": _amount(raw.get("quantity")),
            "remaining_cost": _amount(raw.get("remaining_cost")),
            "contributed_quote": _amount(raw.get("contributed_quote")),
            "disposal_proceeds": _amount(raw.get("disposal_proceeds")),
            "fees": _fees(raw.get("fees")),
            "pending_fee_reports": pending,
            "basis_provenance": (
                raw.get("basis_provenance")
                if raw.get("basis_provenance")
                in {
                    "exchange_fills",
                    "csv_declared_fees_unknown",
                    "unvalued_external_fees",
                    "unknown",
                }
                else "unknown"
            ),
        }
    except (ValueError, TypeError):
        return None


async def accumulation_portfolio(connection: BaseDBAsyncClient) -> dict[str, Any]:
    """Sum exact remaining costs by quote, preserving unknown contributions.

    This covers all persisted accumulation holdings, independently of the registry
    page cursor. It excludes already sold inventory and does not sum currencies.
    """
    rows = await model.OpenTrades.filter(lifecycle_mode="accumulation").using_db(
        connection
    )
    owners = {
        (row.holding_id, row.symbol)
        for row in await model.AccumulationActivation.filter(
            holding_id__in=[row.id for row in rows]
        ).using_db(connection)
    }
    groups: dict[str, dict[str, Any]] = {}
    with localcontext() as context:
        context.prec = 512
        for row in rows:
            quote = row.symbol.split("/")[-1]
            group = groups.setdefault(
                quote,
                {
                    "quote": quote,
                    "holding_count": 0,
                    "known_remaining_cost": Decimal(0),
                    "unknown_cost_count": 0,
                },
            )
            group["holding_count"] += 1
            cost = _amount(row.accumulation_remaining_cost)
            if cost is None:
                group["unknown_cost_count"] += 1
            else:
                group["known_remaining_cost"] += Decimal(cost)
    for group in groups.values():
        group["known_remaining_cost"] = format(group["known_remaining_cost"], "f")
        group["remaining_cost"] = (
            None if group["unknown_cost_count"] else group["known_remaining_cost"]
        )
    return {
        "holding_count": len(rows),
        "unverified_holding_count": sum(
            (row.id, row.symbol) not in owners for row in rows
        ),
        "by_quote": [groups[key] for key in sorted(groups)],
        "valuation_available": False,
    }


async def accumulation_order_history(
    activation: model.AccumulationActivation, connection: BaseDBAsyncClient
) -> dict[str, Any]:
    """Read the latest 20 filled orders, including previous closed generations.

    One row is the latest cumulative checkpoint for one exchange order, not an
    additional fill. Fee-only corrections update it without duplicating proceeds.
    """
    rows = (
        await model.AccumulationFillCheckpoint.filter(activation=activation)
        .exclude(filled="0")
        .using_db(connection)
        .select_related("placement")
        .order_by("-id")
        .limit(21)
    )
    result = []
    for row in rows[:20]:
        try:
            fees = _fees(json.loads(row.fees_json))
        except (ValueError, TypeError):
            fees = None
        placement = row.placement
        result.append(
            {
                "checkpoint_id": row.id,
                "placement_operation_id": placement.operation_id,
                "deal_id": row.deal_id,
                "side": placement.side,
                "filled_quantity": _amount(row.filled),
                "quote_cost": _amount(row.quote_cost),
                "fees": fees,
                "fees_complete": row.fees_complete and fees is not None,
                "terminal": row.terminal,
                "inventory_at_update": _inventory(row.inventory_json),
                "updated_at": row.updated_at.isoformat(),
            }
        )
    return {"orders": result, "older_orders_available": len(rows) > 20}
