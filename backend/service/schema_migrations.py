"""Ordered, resumable schema and data migration runner."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import helper
from model import SchemaMigration
from tortoise import Tortoise

MIGRATION_STATUS_RUNNING = "running"
MIGRATION_STATUS_APPLIED = "applied"
MIGRATION_STATUS_FAILED = "failed"
EXPAND_ONLY_COMPATIBILITY = "expand-only:9a56ed9"
# Marks the first contract (destructive) migration: it rebuilds tables and
# drops columns, so a failed run must never be silently re-planned as an
# additive step.
CONTRACT_DROP_COMPATIBILITY = "contract-drop:2026-11-01-021"
# One-time ledger-hygiene prune (Phase 5): applied ledger rows older than
# this version are deleted on an install that is at the MSV floor, and the
# runner stops re-applying the kept definitions for those rows on that
# database.  The prune row's own checksum gate protects this boundary.
LEDGER_PRUNE_VERSION = "2026-11-09-024-ledger-hygiene-prune"
MAX_MIGRATION_ERROR_LENGTH = 2000

logging = helper.LoggerFactory.get_logger("logs/database.log", "database")


@dataclass(frozen=True)
class MigrationDefinition:
    """Describe one ordered, idempotent migration step."""

    version: str
    phase: str
    description: str
    apply: Callable[[], Awaitable[None]]
    compatibility: str = EXPAND_ONLY_COMPATIBILITY

    @property
    def checksum(self) -> str:
        """Return a stable fingerprint for immutable migration metadata."""
        source = "\n".join(
            (
                self.version,
                self.phase,
                self.description,
                self.compatibility,
            )
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()


async def bootstrap_sqlite_migration_ledger(db_url: str) -> None:
    """Create the ledger before ORM schema generation touches a legacy SQLite DB."""
    if not db_url.startswith("sqlite://"):
        return

    connection = Tortoise.get_connection("default")
    # Bootstrap has no dependency on an ORM model. The expanded table is ignored
    # safely by the previous release throughout the declared compatibility window.
    await connection.execute_script("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version VARCHAR(100) NOT NULL UNIQUE,
            phase VARCHAR(32) NOT NULL,
            description TEXT NOT NULL,
            checksum VARCHAR(64) NOT NULL,
            compatibility VARCHAR(100) NOT NULL,
            status VARCHAR(20) NOT NULL,
            error TEXT NULL,
            started_at TIMESTAMP NULL,
            applied_at TIMESTAMP NULL
        );
        """)


def _validate_migration_order(
    migrations: Sequence[MigrationDefinition],
) -> None:
    """Reject duplicate or non-monotonic migration definitions."""
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise RuntimeError("Schema migration versions must be unique.")
    if versions != sorted(versions):
        raise RuntimeError("Schema migrations must be ordered by version.")


async def _retired_ledger_boundary() -> str | None:
    """Return the prune boundary when the ledger-hygiene prune has applied.

    A pruned database must not re-apply the pre-floor migrations whose rows
    the prune deleted: their definitions stay in the code so unsupported
    installs crossing the floor from below still migrate, but on a pruned
    database the applied prune row is the durable record that those rows are
    retired.  Only *missing* rows are affected: any row that exists,
    including a failed one, is still processed normally, so the checksum
    gate and retry semantics are unchanged.

    Returns:
        The prune version when its ledger row is ``applied``, else ``None``.
    """
    pruned = await SchemaMigration.filter(
        version=LEDGER_PRUNE_VERSION,
        status=MIGRATION_STATUS_APPLIED,
    ).exists()
    return LEDGER_PRUNE_VERSION if pruned else None


async def _mark_failed(
    ledger_row: SchemaMigration,
    exc: BaseException,
) -> None:
    """Persist a bounded failure diagnostic so startup can resume visibly."""
    ledger_row.status = MIGRATION_STATUS_FAILED
    ledger_row.error = str(exc)[:MAX_MIGRATION_ERROR_LENGTH]
    ledger_row.applied_at = None
    await ledger_row.save(
        update_fields=("status", "error", "applied_at"),
    )


async def run_schema_migrations(
    migrations: Sequence[MigrationDefinition],
) -> None:
    """Apply ordered idempotent migrations and record their durable outcome.

    A migration records ``running`` before its side effects. If the process
    stops, the same idempotent callback runs again on restart. A checksum
    mismatch stops startup because changing an already-known migration would
    make recovery ambiguous. A migration whose row is missing but was
    retired by the applied ledger-hygiene prune is skipped: re-applying it on
    a pruned database would recreate the row the prune just deleted.
    """
    _validate_migration_order(migrations)
    retired_boundary = await _retired_ledger_boundary()
    retired_skipped = 0

    for migration in migrations:
        ledger_row = await SchemaMigration.get_or_none(version=migration.version)
        if ledger_row is not None and ledger_row.checksum != migration.checksum:
            raise RuntimeError(
                "Schema migration checksum mismatch for "
                f"{migration.version}; restore the original migration definition."
            )
        if ledger_row is not None and ledger_row.status == MIGRATION_STATUS_APPLIED:
            continue
        if (
            ledger_row is None
            and retired_boundary is not None
            and migration.version < retired_boundary
        ):
            retired_skipped += 1
            continue

        started_at = datetime.now(timezone.utc)
        if ledger_row is None:
            ledger_row = await SchemaMigration.create(
                version=migration.version,
                phase=migration.phase,
                description=migration.description,
                checksum=migration.checksum,
                compatibility=migration.compatibility,
                status=MIGRATION_STATUS_RUNNING,
                started_at=started_at,
            )
        else:
            ledger_row.phase = migration.phase
            ledger_row.description = migration.description
            ledger_row.compatibility = migration.compatibility
            ledger_row.status = MIGRATION_STATUS_RUNNING
            ledger_row.error = None
            ledger_row.started_at = started_at
            ledger_row.applied_at = None
            await ledger_row.save()

        try:
            await migration.apply()
        except asyncio.CancelledError as exc:
            await _mark_failed(ledger_row, exc)
            raise
        except Exception as exc:
            await _mark_failed(ledger_row, exc)
            raise RuntimeError(
                f"Schema migration {migration.version} failed; "
                "restart after correcting the cause to resume safely."
            ) from exc

        ledger_row.status = MIGRATION_STATUS_APPLIED
        ledger_row.error = None
        ledger_row.applied_at = datetime.now(timezone.utc)
        await ledger_row.save(
            update_fields=("status", "error", "applied_at"),
        )

    if retired_skipped:
        logging.info(
            "Ledger hygiene active: skipped %d retired pre-floor migration(s).",
            retired_skipped,
        )
