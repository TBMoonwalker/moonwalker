"""Ordered, resumable schema and data migration runner."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from model import SchemaMigration
from tortoise import Tortoise

MIGRATION_STATUS_RUNNING = "running"
MIGRATION_STATUS_APPLIED = "applied"
MIGRATION_STATUS_FAILED = "failed"
EXPAND_ONLY_COMPATIBILITY = "expand-only:9a56ed9"
MAX_MIGRATION_ERROR_LENGTH = 2000


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

    A migration records ``running`` before its side effects. If the process stops,
    the same idempotent callback runs again on restart. A checksum mismatch stops
    startup because changing an already-known migration would make recovery
    ambiguous.
    """
    _validate_migration_order(migrations)

    for migration in migrations:
        ledger_row = await SchemaMigration.get_or_none(version=migration.version)
        if ledger_row is not None and ledger_row.checksum != migration.checksum:
            raise RuntimeError(
                "Schema migration checksum mismatch for "
                f"{migration.version}; restore the original migration definition."
            )
        if ledger_row is not None and ledger_row.status == MIGRATION_STATUS_APPLIED:
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
