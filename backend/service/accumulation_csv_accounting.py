"""Read fee-aware CSV purchase origins from their adopted lifecycle receipts."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import model
from service.accumulation_fill import AccumulationInventory
from service.accumulation_import import AccumulationImport


@dataclass(frozen=True)
class CSVInventoryOrigin:
    """Declared initial inventory, bound to one registration and holding cycle."""

    activation_id: str
    symbol: str
    deal_id: str
    inventory: AccumulationInventory


async def csv_inventory_origins(
    connection: Any, *, activation_id: Any = None, deal_id: str | None = None
) -> dict[tuple[str, str], CSVInventoryOrigin]:
    """Load only adopted declarations; no CSV row is represented as an exchange fill."""
    query = model.AccumulationLifecycleOperation.filter(
        status="applied",
        action__in=["activate", "retry_entry", "correct_import"],
        request_json__contains='"_csv_deal_id"',
    )
    if activation_id is not None:
        query = query.filter(activation_id=activation_id)
    if deal_id is not None:
        query = query.filter(request_json__contains=deal_id)
    result: dict[tuple[str, str], CSVInventoryOrigin] = {}
    duplicates: set[tuple[str, str]] = set()
    for operation in await query.using_db(connection).select_related("activation"):
        try:
            request = json.loads(operation.request_json)
            adopted = request["_csv_deal_id"]
            UUID(adopted)
            if (
                request["source"] != "csv"
                or request["account_scope"] != operation.activation.account_scope
            ):
                continue
            declaration = AccumulationImport.from_dict(request["imported_inventory"])
            if declaration.symbol != operation.activation.symbol:
                continue
            key = (declaration.symbol, adopted)
            if key in result:
                duplicates.add(key)
            result[key] = CSVInventoryOrigin(
                str(operation.activation_id),
                declaration.symbol,
                adopted,
                declaration.inventory(),
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            continue  # Missing or corrupt evidence never upgrades return completeness.
    return {key: value for key, value in result.items() if key not in duplicates}
