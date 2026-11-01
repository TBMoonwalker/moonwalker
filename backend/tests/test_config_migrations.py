"""Regression tests for versioned configuration migrations."""

from __future__ import annotations

import json

import pytest
from model import AppConfig, ConfigMigration
from service.config_migrations import (
    SIGNAL_SETTINGS_MIGRATION_VERSION,
    run_config_migrations,
)
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_signal_settings_migration_canonicalizes_valid_legacy_json(
    tmp_path,
) -> None:
    """Valid legacy settings should be converted once to stable versioned JSON."""
    db_path = tmp_path / "signal-settings.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    await AppConfig.create(
        key="signal_settings",
        value='{"api_version":"v1","api_url":"https://signals.example"}',
        value_type="str",
    )

    await run_config_migrations()
    await run_config_migrations()

    assert (await AppConfig.get(key="signal_settings")).value == (
        '{"api_url":"https://signals.example","api_version":"v1","schema_version":1}'
    )
    assert (
        await ConfigMigration.filter(version=SIGNAL_SETTINGS_MIGRATION_VERSION).count()
        == 1
    )

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_signal_settings_migration_preserves_malformed_source(
    tmp_path,
) -> None:
    """Malformed legacy settings stay untouched for an explicit readiness block."""
    db_path = tmp_path / "malformed-signal-settings.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    malformed = "{'api_key': 'legacy-python-literal'}"
    await AppConfig.create(
        key="signal_settings",
        value=malformed,
        value_type="str",
    )

    await run_config_migrations()

    assert (await AppConfig.get(key="signal_settings")).value == malformed
    migration = await ConfigMigration.get(version=SIGNAL_SETTINGS_MIGRATION_VERSION)
    assert json.loads(migration.backup_json)[0]["value"] == malformed

    await Tortoise.close_connections()
