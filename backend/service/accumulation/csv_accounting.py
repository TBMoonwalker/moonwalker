"""Read fee-aware CSV purchase origins from their adopted lifecycle receipts."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import model
from service.accumulation.fill import AccumulationInventory
from service.accumulation.imports import AccumulationImport


@dataclass(frozen=True)
class CSVInventoryOrigin:
    """Declared initial inventory, bound to one registration and holding cycle."""

    activation_id: str
    symbol: str
    deal_id: str
    inventory: AccumulationInventory
    declaration: AccumulationImport


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
            if deal_id is not None and adopted != deal_id:
                continue
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
                declaration,
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            continue  # Missing or corrupt evidence never upgrades return completeness.
    return {key: value for key, value in result.items() if key not in duplicates}


async def declared_purchase_history(deal_id: str) -> dict[str, Any]:
    """Project adopted CSV rows for one exact deal without creating executions.

    Validate stored declarations on read. A corrupt, duplicate or absent CSV
    receipt never lends an earlier cycle's purchase evidence to a current one.
    This potentially large projection is only loaded by the history endpoint.
    """
    try:
        normalized = str(UUID(deal_id))
    except (ValueError, TypeError):
        return {"declared_purchases": [], "declaration_status": "none"}
    origins = await csv_inventory_origins(None, deal_id=normalized)
    if len(origins) != 1:
        receipt_exists = await model.AccumulationLifecycleOperation.filter(
            status="applied",
            request_json__contains=normalized,
            action__in=["activate", "retry_entry", "correct_import"],
        ).exists()
        holding = await model.OpenTrades.get_or_none(deal_id=normalized)
        csv_basis = bool(
            holding
            and str(holding.accumulation_basis_provenance or "").startswith("csv")
        )
        return {
            "declared_purchases": [],
            "declaration_status": "unavailable"
            if receipt_exists or csv_basis
            else "none",
        }
    origin = next(iter(origins.values()))
    rows = []
    for index, entry in enumerate(origin.declaration.entries):
        timestamp, price, amount, *extra = entry
        # Reuse the import's fee/quantity semantics for each validated purchase.
        inventory = AccumulationImport(origin.symbol, (entry,), "0", "0").inventory()
        rows.append(
            {
                "key": f"csv-{normalized}-{index}",
                "deal_id": normalized,
                "symbol": origin.symbol,
                "timestamp": str(timestamp),
                "price": price,
                "amount": inventory.quantity,
                "ordersize": inventory.remaining_cost,
                "fees": inventory.fees,
                "fees_known": inventory.pending_fee_reports == 0,
                "provenance": "csv_declaration",
            }
        )
    return {"declared_purchases": rows, "declaration_status": "available"}
