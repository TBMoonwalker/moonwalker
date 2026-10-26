"""Compatible shared strategies for accumulation, retaining legacy history."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import model
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_strategy import (
    CATALOG_PREFIX,
    SUPPORTED_TIMEFRAMES,
    AccumulationParameters,
    effective_accumulation_parameters,
    parse_accumulation_strategy_document,
)
from tortoise.transactions import in_transaction


def _document(value: str) -> AccumulationParameters | None:
    try:
        return parse_accumulation_strategy_document(json.loads(value))
    except (ValueError, TypeError):
        return None


async def list_accumulation_strategies(
    *, after_id: int = 0, limit: int = 50, timeframe: str | None = None
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
            if row.strategy_slug.startswith(CATALOG_PREFIX):
                continue
            parameters = _document(row.ir_json)
            if parameters is None:
                continue
            try:
                parameters = effective_accumulation_parameters(parameters, timeframe)
            except AccumulationStateError:
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
            "defaults": asdict(
                effective_accumulation_parameters(AccumulationParameters(), timeframe)
            ),
            "timeframes": sorted(SUPPORTED_TIMEFRAMES),
        }
