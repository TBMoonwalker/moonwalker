"""Portable accumulation ownership and immutable strategy dependencies.

Restore preserves identities instead of interpreting old events as new signals.
Conflicting local strategy IDs fail closed; restore never overwrites a strategy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import model
from service.accumulation.contracts import AccumulationLifecycle
from tortoise.backends.base.client import BaseDBAsyncClient

ACCUMULATION_TABLE_MODELS: dict[str, type] = {
    "accumulation_activations": model.AccumulationActivation,
    "accumulation_strategy_states": model.AccumulationStrategyState,
    "accumulation_opportunities": model.AccumulationOpportunity,
    "accumulation_attempts": model.AccumulationAttempt,
    "accumulation_lifecycle_operations": model.AccumulationLifecycleOperation,
    "accumulation_fill_checkpoints": model.AccumulationFillCheckpoint,
}
_VERSION_TABLES = {
    "accumulation_activations": "strategy_version_id",
    "accumulation_strategy_states": "strategy_version_id",
    "accumulation_opportunities": "strategy_version_id",
    "accumulation_lifecycle_operations": "target_version_id",
}


def referenced_versions(
    tables: dict[str, Any], config_rows: list[dict[str, Any]] | None = None
) -> set[int]:
    """Collect every historical and current pin, including switch targets."""
    versions = {
        row[field]
        for table, field in _VERSION_TABLES.items()
        for row in tables.get(table, [])
        if row.get(field) is not None
    }
    for row in config_rows or []:
        if (
            row.get("key") != "accumulation_strategy_version_id"
            or row.get("value") is None
        ):
            continue
        value = row["value"]
        if (
            row.get("value_type") != "int"
            or isinstance(value, bool)
            or not str(value).isascii()
            or not str(value).isdigit()
            or len(str(value)) > 19
            or not 0 < int(value) < 2**63
        ):
            raise ValueError("Invalid initial accumulation strategy pin in backup.")
        versions.add(int(value))
    return versions


async def export_strategy_dependencies(
    tables: dict[str, Any],
    connection: BaseDBAsyncClient,
    config_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Export exact pins without unrelated drafts or mutable graph caches."""
    versions = (
        await model.StrategyVersion.filter(
            id__in=referenced_versions(tables, config_rows)
        )
        .using_db(connection)
        .order_by("id")
        .values()
    )
    if {row["id"] for row in versions} != referenced_versions(tables, config_rows):
        raise ValueError("Accumulation backup is missing a selected strategy version.")
    definitions = (
        await model.StrategyDefinition.filter(
            slug__in={row["strategy_slug"] for row in versions}
        )
        .using_db(connection)
        .order_by("id")
        .values()
    )
    if {row["slug"] for row in definitions} != {
        row["strategy_slug"] for row in versions
    }:
        raise ValueError("Accumulation backup is missing a strategy definition.")
    return {"definitions": definitions, "versions": versions}


def _index(rows: Any, key: str = "id") -> dict[Any, dict[str, Any]]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Accumulation backup tables must contain objects.")
    result: dict[Any, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ValueError("Accumulation backup identity is missing or invalid.")
        if value in result:
            raise ValueError("Accumulation backup contains duplicate identities.")
        result[value] = row
    return result


def validate_accumulation_backup(
    tables: dict[str, Any],
    intents: list[dict[str, Any]],
    dependencies: Any,
    config_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reject missing ownership/dependencies before replacing any persisted data."""
    has_accumulation = any(tables.get(name) for name in ACCUMULATION_TABLE_MODELS)
    has_accumulation |= bool(referenced_versions({}, config_rows))
    holdings = tables["open_trades"]
    has_accumulation |= any(
        row.get("lifecycle_mode") == "accumulation" for row in holdings
    )
    if not has_accumulation:
        return {"definitions": [], "versions": []}
    if not isinstance(dependencies, dict):
        raise ValueError("Accumulation backup requires pinned strategy dependencies.")
    definitions = _index(dependencies.get("definitions"), "slug")
    versions = _index(dependencies.get("versions"))
    if referenced_versions(tables, config_rows) != set(versions):
        raise ValueError("Accumulation backup has missing or unrelated strategy pins.")
    for version in versions.values():
        if version.get("strategy_slug") not in definitions:
            raise ValueError("Accumulation strategy definition is missing.")
    indexes = {name: _index(tables[name]) for name in ACCUMULATION_TABLE_MODELS}
    for name, rows in indexes.items():
        required = set(ACCUMULATION_TABLE_MODELS[name]._meta.fields_db_projection)
        if any(set(row) != required for row in rows.values()):
            raise ValueError("Accumulation backup record is incomplete or unsupported.")
    holding_index = _index(holdings)
    placement_index = _index(tables["placement_intents"] + intents)
    activations = indexes["accumulation_activations"]
    opportunities = indexes["accumulation_opportunities"]
    linked_holdings: set[int] = set()
    symbols: set[str] = set()
    for activation in activations.values():
        UUID(activation["id"])
        UUID(activation["generation"])
        AccumulationLifecycle(activation["state"])
        symbol = activation["symbol"]
        if symbol in symbols or not activation.get("account_scope"):
            raise ValueError("Accumulation backup ownership is ambiguous.")
        symbols.add(symbol)
        holding_id = activation.get("holding_id")
        if holding_id is not None:
            holding = holding_index.get(holding_id)
            if (
                holding is None
                or holding.get("lifecycle_mode") != "accumulation"
                or holding["symbol"] != symbol
                or holding_id in linked_holdings
            ):
                raise ValueError("Accumulation holding ownership is invalid.")
            linked_holdings.add(holding_id)
    if linked_holdings != {
        row["id"] for row in holdings if row.get("lifecycle_mode") == "accumulation"
    }:
        raise ValueError("Accumulation holding is missing its activation.")
    owners: dict[int, str] = {}
    for name, rows in indexes.items():
        if name == "accumulation_activations":
            continue
        for row in rows.values():
            if name == "accumulation_attempts":
                opportunity = opportunities.get(row.get("opportunity_id"))
                if opportunity is None:
                    raise ValueError("Accumulation attempt is missing its opportunity.")
                activation_id = opportunity["activation_id"]
            else:
                activation_id = row.get("activation_id")
            activation = activations.get(activation_id)
            if activation is None:
                raise ValueError("Accumulation record is missing its activation.")
            placement_id = row.get("placement_id")
            if placement_id is not None:
                placement = placement_index.get(placement_id)
                if placement is None or placement.get("symbol") != activation["symbol"]:
                    raise ValueError("Accumulation placement ownership is invalid.")
                if name in {
                    "accumulation_attempts",
                    "accumulation_lifecycle_operations",
                }:
                    if placement_id in owners:
                        raise ValueError("Accumulation placement has multiple owners.")
                    owners[placement_id] = activation_id
    for row in indexes["accumulation_fill_checkpoints"].values():
        if owners.get(row["placement_id"]) != row["activation_id"]:
            raise ValueError("Accumulation checkpoint is missing its placement owner.")
    return dependencies


async def restore_strategy_dependencies(
    dependencies: dict[str, Any], connection: BaseDBAsyncClient
) -> None:
    """Merge exact immutable pins or abort the enclosing restore transaction."""
    for row in dependencies["versions"]:
        existing = await model.StrategyVersion.get_or_none(id=row["id"]).using_db(
            connection
        )
        named = await model.StrategyVersion.get_or_none(
            strategy_slug=row["strategy_slug"], version=row["version"]
        ).using_db(connection)
        if existing is not None or named is not None:
            if (
                existing is None
                or named is None
                or existing.id != named.id
                or any(
                    getattr(existing, key) != row[key]
                    for key in (
                        "strategy_slug",
                        "version",
                        "ir_json",
                        "validation_json",
                        "explanation",
                    )
                )
            ):
                raise ValueError(
                    "Restored strategy pin conflicts with the local strategy catalog."
                )
            continue
        await model.StrategyVersion.create(
            using_db=connection,
            created_at=datetime.fromisoformat(row["created_at"]),
            activated_at=(
                datetime.fromisoformat(row["activated_at"])
                if row.get("activated_at") is not None
                else None
            ),
            **{
                key: row[key]
                for key in (
                    "id",
                    "strategy_slug",
                    "version",
                    "ir_json",
                    "validation_json",
                    "explanation",
                )
            },
        )
    for row in dependencies["definitions"]:
        if (
            await model.StrategyDefinition.filter(slug=row["slug"])
            .using_db(connection)
            .exists()
        ):
            continue
        # A portable pin is not permission to publish a catalog default.
        await model.StrategyDefinition.create(
            using_db=connection,
            slug=row["slug"],
            name=row["name"],
            description=row.get("description"),
            active_version=None,
        )


def safe_accumulation_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """Pause restored ownership and invalidate pending executable commands."""
    row = dict(row)
    if table == "accumulation_activations":
        if row["state"] == "enabled":
            row["state"] = "paused"
        row["explicitly_paused"] = True
        row["reason"] = "restore_validation_required"
        row["revision"] += 1
    elif table == "accumulation_lifecycle_operations" and row["status"] == "pending":
        row["status"] = "quarantined"
        row["reason"] = "restore_validation_required"
    elif table == "open_trades" and row.get("lifecycle_mode") == "accumulation":
        row["automation_paused"] = True
    return row
