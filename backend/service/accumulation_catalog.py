"""Immutable accumulation strategy variants in the existing strategy catalog."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import Any

import model
from service.accumulation_commands import validate_operation_id
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_state import AccumulationConflictError
from service.accumulation_strategy import (
    BUILTIN_ACCUMULATION_SLUG,
    CAPABILITY,
    CATALOG_PREFIX,
    SUPPORTED_TIMEFRAMES,
    AccumulationParameters,
    build_accumulation_strategy_document,
    parse_accumulation_strategy_document,
)
from service.database import run_sqlite_write_with_retry
from service.strategy_persistence import _STRATEGY_PROMOTION_LOCK
from service.trading_maintenance import trading_maintenance_barrier
from tortoise.transactions import in_transaction

_BUILTIN_SEED_LOCK = asyncio.Lock()


async def seed_builtin_accumulation_strategy() -> None:
    """Make a starter available before setup without selecting or trading it."""
    document = json.dumps(
        build_accumulation_strategy_document(), sort_keys=True, separators=(",", ":")
    )

    async def persist() -> None:
        async with in_transaction() as connection:
            definition = await model.StrategyDefinition.get_or_none(
                slug=BUILTIN_ACCUMULATION_SLUG
            ).using_db(connection)
            version = await model.StrategyVersion.get_or_none(
                strategy_slug=BUILTIN_ACCUMULATION_SLUG, version=1
            ).using_db(connection)
            if definition is not None or version is not None:
                if (
                    definition is None
                    or not definition.is_builtin
                    or version is None
                    or version.ir_json != document
                ):
                    raise AccumulationStateError(
                        "Built-in accumulation strategy identity requires repair."
                    )
                return
            await model.StrategyDefinition.create(
                using_db=connection,
                slug=BUILTIN_ACCUMULATION_SLUG,
                name="Accumulation dip (ATR)",
                description=(
                    "Volatility-scaled dip accumulation with manual exits. "
                    "Experimental starting parameters; not performance optimized."
                ),
                is_builtin=True,
                active_version=1,
                draft_version=1,
                validation_status="valid",
            )
            await model.StrategyVersion.create(
                using_db=connection,
                strategy_slug=BUILTIN_ACCUMULATION_SLUG,
                version=1,
                ir_json=document,
                validation_json=json.dumps(
                    {"status": "valid", "capability": CAPABILITY}
                ),
                explanation=(
                    "Buy smaller corrections with smaller budget fractions and "
                    "increase spending on deeper ATR-normalized declines. Manual exits only."
                ),
            )

    async with _BUILTIN_SEED_LOCK:
        await run_sqlite_write_with_retry(persist, "seeding accumulation starter")


def _document(value: str) -> AccumulationParameters | None:
    try:
        return parse_accumulation_strategy_document(json.loads(value))
    except (ValueError, TypeError):
        return None


async def list_accumulation_strategies(
    *, after_id: int = 0, limit: int = 50
) -> dict[str, Any]:
    """Return a bounded ID page of compatible immutable versions, including history."""
    if type(after_id) is not int or not 0 <= after_id < 2**63:
        raise AccumulationStateError("Invalid strategy cursor.")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise AccumulationStateError("limit must be between 1 and 100.")
    from service.strategy_persistence import seed_builtin_strategies

    await seed_builtin_strategies()
    async with in_transaction() as connection:
        # Scan bounded batches, including ordinary graphs, so catalog size cannot
        # turn one dashboard poll into unbounded JSON parsing or database work.
        rows = (
            await model.StrategyVersion.filter(id__gt=after_id)
            .using_db(connection)
            .order_by("id")
            .limit(limit + 1)
        )
        names = {
            row.slug: row.name
            for row in await model.StrategyDefinition.filter(
                slug__in=[row.strategy_slug for row in rows[:limit]]
            ).using_db(connection)
        }
        versions = []
        for row in rows[:limit]:
            parameters = _document(row.ir_json)
            if parameters is None:
                continue
            versions.append(
                {
                    "id": row.id,
                    "slug": row.strategy_slug,
                    "name": names.get(row.strategy_slug, row.strategy_slug),
                    "version": row.version,
                    "parameters": {
                        key: getattr(parameters, key)
                        for key in AccumulationParameters.__dataclass_fields__
                    },
                    "required_history_candles": parameters.history_length,
                }
            )
        return {
            "versions": versions,
            "next_after_id": rows[limit - 1].id if len(rows) > limit else None,
            "defaults": asdict(AccumulationParameters()),
            "timeframes": sorted(SUPPORTED_TIMEFRAMES),
        }


async def create_accumulation_strategy(payload: dict[str, Any]) -> dict[str, Any]:
    """Create one immutable variant; retrying the same operation never duplicates it."""
    if not isinstance(payload, dict) or set(payload) != {
        "operation_id",
        "name",
        "parameters",
    }:
        raise AccumulationStateError("Expected operation_id, name and parameters.")
    operation_id = validate_operation_id(payload["operation_id"])
    name = payload["name"]
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise AccumulationStateError("Strategy name must contain 1 to 120 characters.")
    name = name.strip()
    parameters = AccumulationParameters.from_dict(payload["parameters"])
    document = json.dumps(
        build_accumulation_strategy_document(parameters),
        sort_keys=True,
        separators=(",", ":"),
    )
    slug = CATALOG_PREFIX + hashlib.sha256(operation_id.encode()).hexdigest()[:48]

    async def persist() -> dict[str, Any]:
        async with in_transaction() as connection:
            existing = await model.StrategyDefinition.get_or_none(slug=slug).using_db(
                connection
            )
            if existing is not None:
                version = await model.StrategyVersion.get_or_none(
                    strategy_slug=slug, version=1
                ).using_db(connection)
                if (
                    existing.name != name
                    or version is None
                    or version.ir_json != document
                ):
                    raise AccumulationConflictError(
                        "operation_id was already used for a different strategy."
                    )
                return {"id": version.id, "slug": slug, "name": name, "version": 1}
            if (
                await model.StrategyVersion.filter(strategy_slug=slug)
                .using_db(connection)
                .exists()
            ):
                raise AccumulationConflictError("Strategy identity requires repair.")
            await model.StrategyDefinition.create(
                using_db=connection,
                slug=slug,
                name=name,
                is_builtin=False,
                description="Experimental accumulation strategy variant. Manual exits only.",
                active_version=1,
                draft_version=1,
                validation_status="valid",
            )
            version = await model.StrategyVersion.create(
                using_db=connection,
                strategy_slug=slug,
                version=1,
                ir_json=document,
                validation_json=json.dumps(
                    {"status": "valid", "capability": CAPABILITY}
                ),
                explanation="Accumulate more during deeper ATR-normalized corrections. Manual sales only.",
            )
            return {"id": version.id, "slug": slug, "name": name, "version": 1}

    async with trading_maintenance_barrier.operation() as admitted:
        if not admitted:
            raise AccumulationConflictError("Maintenance is active.")
        async with _STRATEGY_PROMOTION_LOCK:
            return await run_sqlite_write_with_retry(
                persist, "creating accumulation strategy"
            )
