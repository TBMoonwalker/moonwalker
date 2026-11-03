"""Versioned, transactional migrations for persisted configuration."""

from __future__ import annotations

import json

from model import AppConfig, ConfigMigration
from service.signal_settings import SignalSettingsError, serialize_signal_settings
from tortoise.transactions import in_transaction

SIGNAL_SETTINGS_MIGRATION_VERSION = "2026-07-signal-settings-v1"


async def run_config_migrations() -> None:
    """Apply all configuration migrations once in atomic transactions.

    The MSV floor marker is not written here: it is recorded during database
    init, before schema history, by :func:`service.msv.record_msv_floor_marker`
    so an interrupted fresh startup cannot leave a false pre-floor baseline.
    """
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
