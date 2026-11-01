"""Versioned, transactional migrations for persisted configuration."""

from __future__ import annotations

import json

from model import AppConfig, ConfigMigration
from service.msv import FLOOR_CONFIG_MIGRATION_ROW, LEGACY_TRADE_MODE_KEYS
from service.signal_settings import SignalSettingsError, serialize_signal_settings
from tortoise.transactions import in_transaction

SIGNAL_SETTINGS_MIGRATION_VERSION = "2026-07-signal-settings-v1"


async def _record_floor_marker() -> None:
    """Persist the MSV floor marker for databases that carry no pre-floor rows.

    The floor release's trade-mode migration is removed: raw pre-4.9 bridge
    keys are dropped on restore instead of canonicalized.  The marker row must
    still be written for clean databases because the MSV preflight
    (``service.msv``) uses its presence to tell a fresh database that has
    reached the floor from a pre-floor one.  A database that still carries the
    legacy bridge rows is left unmarked so it keeps reporting ``unsupported``
    until the operator upgrades through the floor release.
    """
    async with in_transaction() as connection:
        already_applied = (
            await ConfigMigration.filter(version=FLOOR_CONFIG_MIGRATION_ROW)
            .using_db(connection)
            .exists()
        )
        if already_applied:
            return
        legacy_present = (
            await AppConfig.filter(key__in=list(LEGACY_TRADE_MODE_KEYS))
            .using_db(connection)
            .exists()
        )
        if legacy_present:
            return
        await ConfigMigration.create(
            using_db=connection,
            version=FLOOR_CONFIG_MIGRATION_ROW,
            backup_json="[]",
        )


async def run_config_migrations() -> None:
    """Apply all configuration migrations once in atomic transactions."""
    await _record_floor_marker()

    async with in_transaction() as connection:
        already_applied = (
            await ConfigMigration.filter(version=SIGNAL_SETTINGS_MIGRATION_VERSION)
            .using_db(connection)
            .exists()
        )
        if already_applied:
            return

        row = await AppConfig.filter(key="signal_settings").using_db(connection).first()
        backup_rows = []
        if row is not None:
            backup_rows.append(
                {
                    "key": row.key,
                    "value": row.value,
                    "value_type": row.value_type,
                }
            )
            try:
                canonical_value = serialize_signal_settings(row.value)
            except SignalSettingsError:
                canonical_value = None
            if canonical_value is not None:
                await (
                    AppConfig.filter(key="signal_settings")
                    .using_db(connection)
                    .update(
                        value=canonical_value,
                        value_type="str",
                    )
                )

        await ConfigMigration.create(
            using_db=connection,
            version=SIGNAL_SETTINGS_MIGRATION_VERSION,
            backup_json=json.dumps(backup_rows, sort_keys=True),
        )
