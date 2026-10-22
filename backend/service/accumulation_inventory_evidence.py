"""Distinguish a legitimate empty registration from missing recorded coins."""

import json
from decimal import Decimal
from typing import Any

import model
from service.accumulation_commands import ENTRY_ACTIONS
from service.accumulation_import import AccumulationImport


async def inventory_restore_required(activation: Any, connection: Any) -> bool:
    """Use bounded audit evidence; corrupt evidence must never authorize an empty stop."""
    totals = await model.AccumulationReturnTotals.get_or_none(
        activation=activation
    ).using_db(connection)
    checkpoint = (
        await model.AccumulationFillCheckpoint.filter(activation=activation)
        .using_db(connection)
        .order_by("-updated_at", "-id")
        .first()
    )
    try:
        if totals is not None and Decimal(totals.last_quantity) != 0:
            return True
        adjustment = (
            await model.AccumulationLifecycleOperation.filter(
                activation=activation, action="adjust_inventory", status="applied"
            )
            .using_db(connection)
            .order_by("-id")
            .first()
        )
        if adjustment is not None and (
            checkpoint is None or adjustment.updated_at > checkpoint.updated_at
        ):
            return (
                Decimal(json.loads(adjustment.request_json)["after"]["quantity"]) != 0
            )
        if checkpoint is not None:
            if checkpoint.inventory_json is not None:
                return Decimal(json.loads(checkpoint.inventory_json)["quantity"]) != 0
            if Decimal(checkpoint.filled) != 0:
                return True
        entry = (
            await model.AccumulationLifecycleOperation.filter(
                activation=activation, action__in=ENTRY_ACTIONS, status="applied"
            )
            .using_db(connection)
            .order_by("-id")
            .first()
        )
        if entry is not None:
            request = json.loads(entry.request_json)
            if request.get("source") == "csv":
                return (
                    Decimal(
                        AccumulationImport.from_dict(
                            request["imported_inventory"]
                        ).quantity
                    )
                    != 0
                )
        return False
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
        return True
