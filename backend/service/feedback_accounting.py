"""Preserve CCXT fee currencies for final Pathfinder outcome accounting."""

import json
import math
from typing import Any


def execution_fees(fill: dict[str, Any]) -> list[Any]:
    """Return CCXT fee entries once, preferring its multi-fee representation."""
    fees = fill.get("fees") or ([fill["fee"]] if fill.get("fee") else [])
    return fees if isinstance(fees, list) else [fees]


def execution_accounting(fills: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    """Value base/quote fees at execution prices; flag unknown fee currencies."""
    parts = symbol.split("/")
    base, quote = (parts[0], parts[1]) if len(parts) == 2 else ("", "")
    fees_quote = 0.0
    external_buy_fees = 0.0
    sell_fees = 0.0
    complete = bool(fills) and bool(base and quote)
    for fill in fills:
        fees = execution_fees(fill)
        if not isinstance(fees, list) or not fees:
            complete = False
            continue
        if fill.get("side") not in {"buy", "sell"}:
            complete = False
        for fee in fees:
            if not isinstance(fee, dict) or fee.get("cost") is None:
                complete = False
                continue
            try:
                cost = float(fee["cost"])
            except (TypeError, ValueError, OverflowError):
                complete = False
                continue
            currency = str(fee.get("currency") or "").upper()
            if not math.isfinite(cost) or cost < 0:
                complete = False
                continue
            if cost == 0:
                continue
            if currency == quote.upper():
                value = cost
            elif currency == base.upper():
                try:
                    value = cost * float(fill.get("price") or 0)
                except (TypeError, ValueError, OverflowError):
                    complete = False
                    continue
                if value <= 0 or not math.isfinite(value):
                    complete = False
                    continue
            else:
                complete = False
                continue
            fees_quote += value
            if fill.get("side") == "sell":
                sell_fees += value
            elif currency != base.upper():
                # Buy fees in base are already represented by reduced inventory.
                external_buy_fees += value
    return {
        "complete": complete,
        "fees_quote": fees_quote,
        "external_buy_fees": external_buy_fees,
        "sell_fees": sell_fees,
    }


def merge_accounting_metadata(raw: Any, accounting: dict[str, Any]) -> str:
    """Attach fee accounting without losing signal provenance or sizing data."""
    try:
        metadata = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        metadata = None
    return json.dumps(
        {
            **(metadata if isinstance(metadata, dict) else {}),
            "feedback_accounting": accounting,
        },
        sort_keys=True,
    )
