"""Regression tests for the ordered application migration ledger."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
import pytest_asyncio
from model import SchemaMigration
from service.database import Database
from service.schema_migrations import (
    EXPAND_ONLY_COMPATIBILITY,
    MIGRATION_STATUS_APPLIED,
    MIGRATION_STATUS_FAILED,
    MigrationDefinition,
    bootstrap_sqlite_migration_ledger,
    run_schema_migrations,
)
from tortoise import Tortoise

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest_asyncio.fixture(autouse=True)
async def _migration_database(tmp_path):
    db_path = tmp_path / "migration.sqlite"
    db_url = f"sqlite://{db_path}"
    await Tortoise.init(db_url=db_url, modules={"models": ["model"]})
    await bootstrap_sqlite_migration_ledger(db_url)
    await Tortoise.generate_schemas()
    yield db_path
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_ordered_migrations_apply_once_and_keep_expand_compatibility() -> None:
    calls: list[str] = []

    async def first() -> None:
        calls.append("first")

    async def second() -> None:
        calls.append("second")

    migrations = (
        MigrationDefinition("001", "schema", "first expansion", first),
        MigrationDefinition("002", "data", "first backfill", second),
    )

    await run_schema_migrations(migrations)
    await run_schema_migrations(migrations)

    assert calls == ["first", "second"]
    rows = await SchemaMigration.all().order_by("version")
    assert [row.version for row in rows] == ["001", "002"]
    assert {row.status for row in rows} == {MIGRATION_STATUS_APPLIED}
    assert {row.compatibility for row in rows} == {EXPAND_ONLY_COMPATIBILITY}


@pytest.mark.asyncio
async def test_interrupted_migration_resumes_idempotently() -> None:
    attempts = 0
    durable_side_effects: set[str] = set()

    async def resumable() -> None:
        nonlocal attempts
        attempts += 1
        durable_side_effects.add("expanded")
        if attempts == 1:
            raise OSError("simulated process interruption")

    migration = MigrationDefinition(
        "001",
        "schema",
        "resumable expansion",
        resumable,
    )

    with pytest.raises(RuntimeError, match="restart.*resume safely"):
        await run_schema_migrations((migration,))

    failed = await SchemaMigration.get(version="001")
    assert failed.status == MIGRATION_STATUS_FAILED
    assert failed.error == "simulated process interruption"

    await run_schema_migrations((migration,))

    applied = await SchemaMigration.get(version="001")
    assert applied.status == MIGRATION_STATUS_APPLIED
    assert applied.error is None
    assert attempts == 2
    assert durable_side_effects == {"expanded"}


@pytest.mark.asyncio
async def test_changed_applied_migration_fails_closed() -> None:
    async def no_op() -> None:
        return None

    await run_schema_migrations(
        (MigrationDefinition("001", "schema", "original", no_op),)
    )

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        await run_schema_migrations(
            (MigrationDefinition("001", "schema", "changed", no_op),)
        )


@pytest.mark.asyncio
async def test_migrations_reject_non_monotonic_versions() -> None:
    async def no_op() -> None:
        return None

    with pytest.raises(RuntimeError, match="ordered by version"):
        await run_schema_migrations(
            (
                MigrationDefinition("002", "schema", "second", no_op),
                MigrationDefinition("001", "schema", "first", no_op),
            )
        )


@pytest.mark.asyncio
async def test_bootstrap_ledger_exists_before_orm_schema_generation(
    tmp_path,
) -> None:
    await Tortoise.close_connections()
    db_path = tmp_path / "bootstrap.sqlite"
    db_url = f"sqlite://{db_path}"
    await Tortoise.init(db_url=db_url, modules={"models": ["model"]})

    await bootstrap_sqlite_migration_ledger(db_url)

    connection = Tortoise.get_connection("default")
    _, rows = await connection.execute_query(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name = 'schema_migrations'"
    )
    assert [row["name"] for row in rows] == ["schema_migrations"]
    assert os.path.exists(db_path)


@pytest.mark.asyncio
async def test_prior_release_fixture_resumes_and_migrates_idempotently(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supported prior-release database survives interruption and repeat startup."""
    await Tortoise.close_connections()
    db_path = tmp_path / "legacy-v4.3.0.sqlite"
    fixture_sql = (FIXTURE_DIR / "legacy_v4_3_0.sql").read_text(encoding="utf-8")
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(fixture_sql)
        connection.commit()

    monkeypatch.setenv("MOONWALKER_DB_URL", f"sqlite://{db_path}")
    original_backfill = Database._backfill_trade_ledger_rows
    attempts = 0

    async def interrupted_backfill(database: Database) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated legacy backfill interruption")
        await original_backfill(database)

    monkeypatch.setattr(
        Database,
        "_backfill_trade_ledger_rows",
        interrupted_backfill,
    )

    interrupted_database = Database()
    with pytest.raises(RuntimeError, match="restart.*resume safely"):
        await interrupted_database.init()
    await interrupted_database.shutdown()
    await Tortoise.close_connections()

    resumed_database = Database()
    await resumed_database.init()
    await resumed_database.shutdown()
    await Tortoise.close_connections()

    repeated_database = Database()
    await repeated_database.init()
    await repeated_database.shutdown()
    await Tortoise.close_connections()

    assert attempts == 2
    with closing(sqlite3.connect(db_path)) as connection:
        ledger_rows = connection.execute(
            "SELECT version, status FROM schema_migrations ORDER BY version"
        ).fetchall()
        open_trade = connection.execute(
            "SELECT symbol, amount, cost, deal_id, execution_history_complete "
            "FROM opentrades WHERE symbol = 'BTC/USDC'"
        ).fetchone()
        trade = connection.execute(
            "SELECT symbol, orderid, deal_id FROM trades " "WHERE symbol = 'BTC/USDC'"
        ).fetchone()
        executions = connection.execute(
            "SELECT symbol, order_id, role FROM tradeexecutions "
            "WHERE symbol = 'BTC/USDC'"
        ).fetchall()
        legacy_closed_trade = connection.execute(
            "SELECT symbol, profit, amount, cost, close_date "
            "FROM closedtrades WHERE symbol = 'ETH/USDC'"
        ).fetchone()
        ai_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('ai_trust_predictions')"
            ).fetchall()
        }
        upnl_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('upnl_history')"
            ).fetchall()
        }
        execution_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('tradeexecutions')"
            ).fetchall()
        }
        execution_index_columns = {
            tuple(
                column[2]
                for column in connection.execute(
                    f"PRAGMA index_info('{index_row[1]}')"
                ).fetchall()
            )
            for index_row in connection.execute(
                "PRAGMA index_list('tradeexecutions')"
            ).fetchall()
        }

    assert len(ledger_rows) == 8
    assert {status for _, status in ledger_rows} == {MIGRATION_STATUS_APPLIED}
    assert open_trade is not None
    assert open_trade[:3] == ("BTC/USDC", 1.0, 100.0)
    assert open_trade[3]
    assert open_trade[4] == 1
    assert trade == ("BTC/USDC", "legacy-buy-1", open_trade[3])
    assert executions == [("BTC/USDC", "legacy-buy-1", "base_order")]
    assert legacy_closed_trade == (
        "ETH/USDC",
        4.0,
        2.0,
        100.0,
        "2024-05-02 09:00:00+00:00",
    )
    assert "evaluation_id" in ai_columns
    assert "funds_locked" in upnl_columns
    assert {"strategy_slug", "strategy_version"} <= execution_columns
    assert ("strategy_slug", "strategy_version") in execution_index_columns
