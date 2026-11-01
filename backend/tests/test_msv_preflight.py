"""Regression tests for the minimum-supported-version (MSV) preflight."""

from __future__ import annotations

import pytest
import pytest_asyncio
from model import AppConfig, ConfigMigration
from service.config_migrations import run_config_migrations
from service.msv import (
    FLOOR_CONFIG_MIGRATION_ROW,
    MsvStatus,
    evaluate_msv_baseline,
    get_msv_baseline,
    preflight_msv,
    set_msv_baseline,
)
from service.schema_migrations import (
    MigrationDefinition,
    bootstrap_sqlite_migration_ledger,
    run_schema_migrations,
)
from tortoise import Tortoise


@pytest_asyncio.fixture(autouse=True)
async def _migration_database(tmp_path):
    """Give every test a fresh, schema-generated ledger database."""
    db_path = tmp_path / "msv.sqlite"
    db_url = f"sqlite://{db_path}"
    await Tortoise.init(db_url=db_url, modules={"models": ["model"]})
    await bootstrap_sqlite_migration_ledger(db_url)
    await Tortoise.generate_schemas()
    set_msv_baseline(None)
    yield db_path
    set_msv_baseline(None)
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_evaluate_msv_baseline_derives_each_outcome() -> None:
    """Pure decision: floor present wins; otherwise freshness separates cases."""
    assert evaluate_msv_baseline(True, True).status == MsvStatus.SUPPORTED
    assert evaluate_msv_baseline(True, False).status == MsvStatus.SUPPORTED
    assert evaluate_msv_baseline(False, True).status == MsvStatus.UNSUPPORTED
    assert evaluate_msv_baseline(False, False).status == MsvStatus.FRESH


@pytest.mark.asyncio
async def test_evaluate_msv_baseline_fresh_is_supported_and_needs_no_upgrade() -> None:
    baseline = evaluate_msv_baseline(False, False)
    assert baseline.supported is True
    assert baseline.upgrade_guidance == ""


@pytest.mark.asyncio
async def test_evaluate_msv_baseline_pre_floor_is_unsupported_and_guides() -> None:
    baseline = evaluate_msv_baseline(False, True)
    assert baseline.supported is False
    assert baseline.upgrade_guidance
    assert "4.9.0.0" in baseline.summary
    assert baseline.floor_config_migration


@pytest.mark.asyncio
async def test_preflight_msv_fresh_database_is_supported() -> None:
    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.FRESH
    assert baseline.supported is True
    assert get_msv_baseline() is baseline
    assert baseline.upgrade_guidance == ""


@pytest.mark.asyncio
async def test_preflight_msv_schema_history_without_floor_is_unsupported() -> None:
    """History that predates the floor is reported, never blocked."""

    async def _noop() -> None:
        return None

    await run_schema_migrations(
        (MigrationDefinition("000-test-history", "schema", "seed history", _noop),)
    )
    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.UNSUPPORTED
    assert baseline.schema_history_present is True
    assert baseline.floor_applied is False
    assert baseline.supported is False
    assert baseline.upgrade_guidance
    # The report did not mutate the ledger: still no floor row.
    assert (
        await ConfigMigration.filter(version="2026-09-sidestep-removal-v1").exists()
        is False
    )


@pytest.mark.asyncio
async def test_preflight_msv_floor_migration_present_is_supported() -> None:
    await ConfigMigration.create(
        version="2026-09-sidestep-removal-v1",
        backup_json="[]",
    )
    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.SUPPORTED
    assert baseline.floor_applied is True
    assert baseline.supported is True
    assert get_msv_baseline() is baseline


@pytest.mark.asyncio
async def test_get_msv_baseline_is_none_before_preflight() -> None:
    assert get_msv_baseline() is None


@pytest.mark.asyncio
async def test_floor_marker_keeps_a_fresh_install_supported_on_later_startups() -> None:
    """A clean database receives the floor marker so startup 2 is not pre-floor."""
    await run_config_migrations()

    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.SUPPORTED
    assert baseline.floor_applied is True
    assert baseline.supported is True


@pytest.mark.asyncio
async def test_floor_marker_is_not_written_while_legacy_bridge_rows_exist() -> None:
    """Pre-floor residue keeps the database unmarked and unsupported."""

    async def _noop() -> None:
        return None

    await AppConfig.create(
        key="trade_lifecycle_mode", value="classic_dca", value_type="str"
    )
    await run_schema_migrations(
        (MigrationDefinition("000-test-history", "schema", "seed history", _noop),)
    )
    await run_config_migrations()

    assert (
        await ConfigMigration.filter(version=FLOOR_CONFIG_MIGRATION_ROW).exists()
        is False
    )
    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.UNSUPPORTED
    assert baseline.floor_applied is False
