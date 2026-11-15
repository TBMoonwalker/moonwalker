"""Regression tests for the minimum-supported-version (MSV) preflight."""

from __future__ import annotations

import pytest
import pytest_asyncio
from model import AppConfig, ConfigMigration
from service.msv import (
    FLOOR_CONFIG_MIGRATION_ROW,
    MINIMUM_SUPPORTED_VERSION,
    MsvStatus,
    evaluate_msv_baseline,
    get_msv_baseline,
    preflight_msv,
    record_msv_floor_marker,
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


async def _seed_schema_history() -> None:
    async def _noop() -> None:
        return None

    await run_schema_migrations(
        (MigrationDefinition("000-test-history", "schema", "seed history", _noop),)
    )


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
    assert MINIMUM_SUPPORTED_VERSION in baseline.summary
    assert "6.3.0.0" in baseline.upgrade_guidance
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
    await _seed_schema_history()
    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.UNSUPPORTED
    assert baseline.schema_history_present is True
    assert baseline.floor_applied is False
    assert baseline.supported is False
    assert baseline.upgrade_guidance
    # The report did not mutate the ledger: still no floor row.
    assert (
        await ConfigMigration.filter(version=FLOOR_CONFIG_MIGRATION_ROW).exists()
        is False
    )


@pytest.mark.asyncio
async def test_preflight_msv_floor_migration_present_is_supported() -> None:
    await ConfigMigration.create(
        version=FLOOR_CONFIG_MIGRATION_ROW,
        backup_json="[]",
    )
    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.SUPPORTED
    assert baseline.floor_applied is True
    assert baseline.supported is True
    assert get_msv_baseline() is baseline


@pytest.mark.asyncio
async def test_preflight_msv_pruned_ledger_stays_supported() -> None:
    """A pruned database (floor row, empty schema history) is still supported.

    The ledger-hygiene prune deletes every older schema-migration row; the
    preflight must keep classifying the install as supported on the floor
    row alone, never as fresh.
    """
    await ConfigMigration.create(
        version=FLOOR_CONFIG_MIGRATION_ROW,
        backup_json="[]",
    )
    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.SUPPORTED
    assert baseline.floor_applied is True
    assert baseline.schema_history_present is False
    assert baseline.supported is True
    assert baseline.upgrade_guidance == ""


@pytest.mark.asyncio
async def test_get_msv_baseline_is_none_before_preflight() -> None:
    assert get_msv_baseline() is None


@pytest.mark.asyncio
async def test_floor_marker_keeps_a_fresh_install_supported_on_later_startups() -> None:
    """A clean database is marked at the floor during init, so startup 2 is not pre-floor."""
    # The preflight runs before schema migrations and classifies a clean
    # database as fresh; record_msv_floor_marker then marks it at the floor.
    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.FRESH
    await record_msv_floor_marker(baseline)

    baseline2 = await preflight_msv()
    assert baseline2.status == MsvStatus.SUPPORTED
    assert baseline2.floor_applied is True
    assert baseline2.supported is True


@pytest.mark.asyncio
async def test_floor_marker_is_withheld_for_fresh_install_with_legacy_rows() -> None:
    """A database with legacy rows must not be self-marked as supported."""
    await AppConfig.create(
        key="trade_lifecycle_mode", value="classic_dca", value_type="str"
    )
    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.UNSUPPORTED
    assert not baseline.supported
    assert baseline.upgrade_guidance
    await record_msv_floor_marker(baseline)

    assert not await ConfigMigration.filter(version=FLOOR_CONFIG_MIGRATION_ROW).exists()
    await _seed_schema_history()
    baseline2 = await preflight_msv()
    assert baseline2.status == MsvStatus.UNSUPPORTED
    assert baseline2.floor_applied is False


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_rows", [False, True])
async def test_floor_marker_preserves_pre_floor_warning_across_startups(
    legacy_rows: bool,
) -> None:
    """Starting newer software alone cannot prove old data is compatible."""
    if legacy_rows:
        await AppConfig.create(
            key="trade_lifecycle_mode", value="classic_dca", value_type="str"
        )
    await _seed_schema_history()
    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.UNSUPPORTED
    assert baseline.upgrade_guidance

    await record_msv_floor_marker(baseline)

    assert not await ConfigMigration.filter(version=FLOOR_CONFIG_MIGRATION_ROW).exists()
    baseline2 = await preflight_msv()
    assert baseline2.status == MsvStatus.UNSUPPORTED
    assert baseline2.floor_applied is False
    assert baseline2.supported is False
    assert baseline2.upgrade_guidance


@pytest.mark.asyncio
async def test_floor_marker_is_withheld_without_a_preflight_baseline() -> None:
    """Without a preflight baseline the marker is withheld (fail closed)."""
    await record_msv_floor_marker(None)
    assert (
        await ConfigMigration.filter(version=FLOOR_CONFIG_MIGRATION_ROW).exists()
        is False
    )


@pytest.mark.asyncio
async def test_floor_marker_written_before_schema_history_survives_an_interrupted_startup() -> (
    None
):
    """An interrupted fresh startup cannot leave a false pre-floor baseline.

    Regression: the marker was previously written by config loading, which runs
    AFTER schema migrations. A fresh install interrupted between the two had
    schema history but no marker, so its next startup reported ``unsupported``
    and the marker guard refused to ever mark it. Recording the marker before
    schema history closes that window.
    """
    baseline = await preflight_msv()
    assert baseline.status == MsvStatus.FRESH
    # Init records the marker before schema migrations commit their rows...
    await record_msv_floor_marker(baseline)
    # ...then the schema migrations run. If startup stops right here (schema
    # history present, but the marker is already committed)...
    await _seed_schema_history()
    # ...the next startup sees the floor row and reports supported, not a
    # false pre-floor baseline.
    baseline2 = await preflight_msv()
    assert baseline2.status == MsvStatus.SUPPORTED
    assert baseline2.floor_applied is True
    assert baseline2.schema_history_present is True
    assert baseline2.supported is True
    assert baseline2.upgrade_guidance == ""
