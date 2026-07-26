"""Regression tests for versioned configuration migrations."""

from __future__ import annotations

import json

import pytest
from model import AppConfig, ConfigMigration
from service.config import Config
from service.config_migrations import (
    SIGNAL_SETTINGS_MIGRATION_VERSION,
    TRADE_MODE_MIGRATION_VERSION,
    run_config_migrations,
)
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_trade_mode_migration_is_versioned_idempotent_and_recoverable(
    tmp_path,
) -> None:
    """Legacy rows should gain one canonical mode and a recovery snapshot."""
    db_path = tmp_path / "legacy.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    await AppConfig.create(
        key="trade_lifecycle_mode",
        value="sidestep_reentry",
        value_type="str",
    )
    await AppConfig.create(
        key="sidestep_campaign_enabled",
        value=True,
        value_type="bool",
    )

    config = Config()
    await config.load_all()
    await config.load_all()

    assert config.get("trade_mode") == "sidestep"
    assert await AppConfig.filter(key="trade_mode").count() == 1
    migration = await ConfigMigration.get(version=TRADE_MODE_MIGRATION_VERSION)
    assert json.loads(migration.backup_json) == [
        {
            "key": "sidestep_campaign_enabled",
            "value": "True",
            "value_type": "bool",
        },
        {
            "key": "trade_lifecycle_mode",
            "value": "sidestep_reentry",
            "value_type": "str",
        },
    ]
    assert (
        await ConfigMigration.filter(version=TRADE_MODE_MIGRATION_VERSION).count() == 1
    )

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_trade_mode_migration_rolls_back_and_retries_after_interruption(
    tmp_path,
    monkeypatch,
) -> None:
    """A failed ledger write must roll back the canonical config mutation."""
    db_path = tmp_path / "interrupted.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    await AppConfig.create(
        key="dynamic_dca",
        value=True,
        value_type="bool",
    )

    original_create = ConfigMigration.create

    async def fail_create(cls, **_kwargs):
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(ConfigMigration, "create", classmethod(fail_create))
    with pytest.raises(RuntimeError, match="simulated interruption"):
        await run_config_migrations()

    assert await AppConfig.filter(key="trade_mode").exists() is False
    assert await ConfigMigration.all().count() == 0

    monkeypatch.setattr(ConfigMigration, "create", original_create)
    await run_config_migrations()

    assert (await AppConfig.get(key="trade_mode")).value == "dynamic_dca"
    assert (
        await ConfigMigration.filter(version=TRADE_MODE_MIGRATION_VERSION).count() == 1
    )

    await Tortoise.close_connections()


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
        '{"api_url":"https://signals.example","api_version":"v1",' '"schema_version":1}'
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
