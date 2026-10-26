"""Transactional storage primitives for future accumulation lifecycle services.

No function here activates a symbol or submits an exchange order. Callers must
validate market inputs and ownership before creating an activation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import model
from service.accumulation.contracts import (
    OBSERVATION_SCHEMA_VERSION,
    AccumulationIdentity,
    AccumulationStateError,
    decode_observations,
    encode_observations,
)
from service.database import run_sqlite_write_with_retry
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction


class AccumulationConflictError(AccumulationStateError):
    """An evaluated decision no longer owns the persisted activation revision."""


@dataclass(frozen=True)
class AccumulationContext:
    """A consistent pinned identity and optional first-use observation state."""

    identity: AccumulationIdentity
    observations: dict[str, Any] | None
    last_processed_close_ms: int | None


async def _load_context(
    activation_id: str,
    account_scope: str,
    connection: BaseDBAsyncClient,
) -> AccumulationContext:
    activation = await model.AccumulationActivation.get_or_none(
        id=activation_id
    ).using_db(connection)
    if activation is None or activation.account_scope != account_scope:
        raise AccumulationStateError("Activation is missing or account scope changed.")
    version = await model.StrategyVersion.get_or_none(
        id=activation.strategy_version_id
    ).using_db(connection)
    if version is None:
        raise AccumulationStateError("Activation has no pinned strategy version.")
    baseline_close_ms = activation.baseline_close_ms
    if baseline_close_ms is None and not activation.observations_initialized:
        # Legacy first fills cleared the baseline while invalidating observations.
        # Zero is only an in-memory floor for rebuilding from fresh inputs; the
        # verified rebase persists a real candle baseline before evaluation.
        baseline_close_ms = 0
    identity = AccumulationIdentity.from_dict(
        {
            "activation_id": str(activation.id),
            "account_scope": activation.account_scope,
            "generation": str(activation.generation),
            "state": activation.state,
            "explicitly_paused": activation.explicitly_paused,
            "strategy_version_id": version.id,
            "strategy_slug": version.strategy_slug,
            "strategy_version": version.version,
            "observation_epoch": activation.observation_epoch,
            "baseline_close_ms": baseline_close_ms,
            "revision": activation.revision,
            "consumption_revision": activation.consumption_revision,
        }
    )
    row = await model.AccumulationStrategyState.get_or_none(
        activation_id=activation.id,
        strategy_version_id=version.id,
        observation_epoch=activation.observation_epoch,
    ).using_db(connection)
    if (row is not None) != activation.observations_initialized:
        raise AccumulationStateError("Observation state is missing or inconsistent.")
    if row is None:
        return AccumulationContext(identity, None, None)
    if row.last_processed_close_ms < identity.baseline_close_ms:
        raise AccumulationStateError(
            "Observation state predates its activation baseline."
        )
    return AccumulationContext(
        identity,
        decode_observations(row.value_json, row.schema_version),
        row.last_processed_close_ms,
    )


async def load_accumulation_context(
    activation_id: str, account_scope: str
) -> AccumulationContext:
    """Read a coherent pinned context; database failures never become empty state."""
    async with in_transaction() as connection:
        return await _load_context(activation_id, account_scope, connection)


async def save_accumulation_observations(
    expected: AccumulationIdentity,
    observations: dict[str, Any],
    last_processed_close_ms: int,
) -> AccumulationIdentity:
    """Persist bounded observations only while the entire decision identity matches.

    The activation revision and observation write commit together. Returning a
    new identity forces callers to refresh after any concurrent lifecycle edit.
    Execution guards and consumption revisions are deliberately never reset.
    """
    value_json = encode_observations(observations)
    if type(last_processed_close_ms) is not int or last_processed_close_ms < 0:
        raise AccumulationStateError("Invalid processed candle timestamp.")

    async def persist() -> AccumulationIdentity:
        async with in_transaction() as connection:
            current = await _load_context(
                expected.activation_id, expected.account_scope, connection
            )
            if current.identity != expected:
                raise AccumulationConflictError(
                    "Accumulation identity changed; reload."
                )
            minimum_close = max(
                expected.baseline_close_ms,
                current.last_processed_close_ms or 0,
            )
            if last_processed_close_ms < minimum_close:
                raise AccumulationConflictError(
                    "Observation timestamp cannot move back."
                )
            updated = (
                await model.AccumulationActivation.filter(
                    id=expected.activation_id, revision=expected.revision
                )
                .using_db(connection)
                .update(revision=expected.revision + 1, observations_initialized=True)
            )
            if updated != 1:
                raise AccumulationConflictError(
                    "Accumulation revision changed; reload."
                )
            await model.AccumulationStrategyState.update_or_create(
                activation_id=expected.activation_id,
                strategy_version_id=expected.strategy_version_id,
                observation_epoch=expected.observation_epoch,
                defaults={
                    "schema_version": OBSERVATION_SCHEMA_VERSION,
                    "value_json": value_json,
                    "last_processed_close_ms": last_processed_close_ms,
                    "revision": expected.revision + 1,
                },
                using_db=connection,
            )
            return replace(expected, revision=expected.revision + 1)

    return await run_sqlite_write_with_retry(
        persist, "saving accumulation observations"
    )
