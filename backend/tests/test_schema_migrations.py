"""Regression tests for the ordered application migration ledger."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import model
import pytest
import pytest_asyncio
from model import SchemaMigration, UnsellableTrades
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


@pytest.mark.asyncio
async def test_closed_trade_mode_backfill_requires_matching_deal_evidence(
    _migration_database,
) -> None:
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC", account_scope="test"
    )
    placement = await model.PlacementIntent.create(
        operation_id="backfill",
        symbol="BTC/USDC",
        exchange_name="test",
        side="buy",
        action="buy",
        order_type="market",
        state="accepted",
    )
    await model.AccumulationFillCheckpoint.create(
        activation=activation, placement=placement, deal_id="known", evidence_json="{}"
    )
    known = await model.ClosedTrades.create(symbol="BTC/USDC", deal_id="known")
    wrong_symbol = await model.ClosedTrades.create(symbol="ETH/USDC", deal_id="wrong")
    unknown = await model.ClosedTrades.create(symbol="SOL/USDC", deal_id="unknown")
    explicit = await model.ClosedTrades.create(
        symbol="BTC/USDC", deal_id="explicit", lifecycle_mode="classic_dca"
    )
    other = await model.PlacementIntent.create(
        operation_id="backfill-wrong",
        symbol="BTC/USDC",
        exchange_name="test",
        side="buy",
        action="buy",
        order_type="market",
        state="accepted",
    )
    await model.AccumulationFillCheckpoint.create(
        activation=activation, placement=other, deal_id="wrong", evidence_json="{}"
    )
    explicit_placement = await model.PlacementIntent.create(
        operation_id="backfill-explicit",
        symbol="BTC/USDC",
        exchange_name="test",
        side="buy",
        action="buy",
        order_type="market",
        state="accepted",
    )
    await model.AccumulationFillCheckpoint.create(
        activation=activation,
        placement=explicit_placement,
        deal_id="explicit",
        evidence_json="{}",
    )

    database = Database()
    database.db_url = f"sqlite://{_migration_database}"
    await database._ensure_closed_trade_mode()
    await database._ensure_closed_trade_mode()
    await known.refresh_from_db()
    await wrong_symbol.refresh_from_db()
    await unknown.refresh_from_db()
    await explicit.refresh_from_db()
    assert known.lifecycle_mode == "accumulation"
    assert wrong_symbol.lifecycle_mode is None
    assert unknown.lifecycle_mode is None
    assert explicit.lifecycle_mode == "classic_dca"


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
    """A supported 4.9 database survives interruption, drop, and repeat startup."""
    await Tortoise.close_connections()
    db_path = tmp_path / "legacy-v4.9.0.sqlite"
    fixture_sql = (FIXTURE_DIR / "legacy_v4_9_0.sql").read_text(encoding="utf-8")
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
        accumulation_defaults = connection.execute(
            "SELECT lifecycle_mode, accumulation_net_quantity, "
            "accumulation_remaining_cost, accumulation_contributed_quote "
            "FROM opentrades WHERE symbol = 'BTC/USDC'"
        ).fetchone()
        accumulation_tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name LIKE 'accumulation_%'"
        ).fetchall()
        trade = connection.execute(
            "SELECT symbol, orderid, deal_id FROM trades WHERE symbol = 'BTC/USDC'"
        ).fetchone()
        executions = connection.execute(
            "SELECT symbol, order_id, role FROM tradeexecutions "
            "WHERE symbol = 'BTC/USDC'"
        ).fetchall()
        legacy_closed_trade = connection.execute(
            "SELECT symbol, profit, amount, cost, close_date, deal_id, close_reason "
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
        dropped_columns = {
            table: {
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info('{table}')"
                ).fetchall()
            }
            for table in (
                "opentrades",
                "trades",
                "closedtrades",
                "tradeexecutions",
                "placement_intents",
            )
        }
        remaining_indexes = {
            row[1]
            for table in ("trades", "closedtrades", "tradeexecutions")
            for row in connection.execute(f"PRAGMA index_list('{table}')").fetchall()
            if row[1]
        }
        spotcampaigns = connection.execute(
            "SELECT campaign_id, symbol, state FROM spotcampaigns"
        ).fetchall()
        placement_intent = connection.execute(
            "SELECT operation_id, client_order_id, exchange_name, symbol, "
            "deal_id, state FROM placement_intents"
        ).fetchone()
        placement_indexes = {
            tuple(
                column[2]
                for column in connection.execute(
                    f"PRAGMA index_info('{index_row[1]}')"
                ).fetchall()
            ): index_row[2]
            for index_row in connection.execute(
                "PRAGMA index_list('placement_intents')"
            ).fetchall()
            if index_row[1]
        }
        placement_triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = 'placement_intents'"
            ).fetchall()
        }

    assert len(ledger_rows) == 20
    assert ("2026-11-01-021-campaign-column-drop", "applied") in ledger_rows
    assert ("2026-10-28-020-manual-stop-valuation", "applied") in ledger_rows
    assert "2026-10-27-019-accumulation-contributions" in {
        version for version, _ in ledger_rows
    }
    assert "2026-10-27-017-closed-trade-mode" in {version for version, _ in ledger_rows}
    assert "2026-10-21-013-accumulation-return-totals" in {
        version for version, _ in ledger_rows
    }
    assert {status for _, status in ledger_rows} == {MIGRATION_STATUS_APPLIED}
    assert accumulation_defaults == ("classic_dca", None, None, None)
    assert len(accumulation_tables) == 9
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
        "legacy-deal-eth-usdc",
        "take_profit",
    )
    assert "evaluation_id" in ai_columns
    assert "funds_locked" in upnl_columns
    assert {"strategy_slug", "strategy_version"} <= execution_columns
    assert ("strategy_slug", "strategy_version") in execution_index_columns
    # The contract migration dropped the campaign channel from every table.
    for table, columns in dropped_columns.items():
        assert "campaign_id" not in columns, table
    assert not (
        {
            "reserved_reentry_quote",
            "waiting_reference_price",
            "waiting_reference_amount",
            "waiting_reference_quote",
            "virtual_waiting_profit",
            "virtual_waiting_profit_percent",
            "last_transition_at",
        }
        & dropped_columns["opentrades"]
    )
    assert "exposure_state" in dropped_columns["opentrades"]
    assert "lifecycle_mode" in dropped_columns["opentrades"]
    # Campaign indexes died with their tables; named survivors were recreated.
    assert not any("campaign" in name for name in remaining_indexes)
    assert "idx_trades_deal_id_timestamp" in remaining_indexes
    assert "idx_closedtrades_close_reason" in remaining_indexes
    assert "idx_tradeexecutions_deal_time" in remaining_indexes
    # The orphan campaign table and its rows are intentionally untouched.
    assert spotcampaigns == [("campaign-eth-usdc-2024", "ETH/USDC", "exited")]
    # A populated placement_intents survives the rebuild with its row data,
    # unique constraints and named indexes intact.
    assert placement_intent == (
        "op-legacy-1",
        "cli-legacy-1",
        "binance",
        "BTC/USDC",
        "legacy-deal-btc-usdc",
        "submitted",
    )
    assert placement_indexes[("operation_id",)] == 1
    assert placement_indexes[("client_order_id",)] == 1
    assert ("state", "symbol") in placement_indexes
    assert ("exchange_order_id",) in placement_indexes
    assert ("deal_id",) in placement_indexes
    # The history-revision trigger created by the accumulation migrations
    # survives the rebuild: real installs carry it, and the drop must not
    # silently lose it.
    assert "history_revision_placement_intents_identity" in placement_triggers


@pytest.mark.asyncio
async def test_contract_drop_migration_resumes_after_interruption(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupted contract drop re-runs cleanly and keeps every row."""
    await Tortoise.close_connections()
    db_path = tmp_path / "legacy-v4.9.0.sqlite"
    fixture_sql = (FIXTURE_DIR / "legacy_v4_9_0.sql").read_text(encoding="utf-8")
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(fixture_sql)
        connection.commit()

    monkeypatch.setenv("MOONWALKER_DB_URL", f"sqlite://{db_path}")
    original_drop = Database._drop_legacy_campaign_columns
    attempts = 0

    async def interrupted_drop(database: Database) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated contract migration interruption")
        await original_drop(database)

    monkeypatch.setattr(Database, "_drop_legacy_campaign_columns", interrupted_drop)

    interrupted_database = Database()
    with pytest.raises(RuntimeError, match="restart.*resume safely"):
        await interrupted_database.init()
    await interrupted_database.shutdown()
    await Tortoise.close_connections()

    # The interrupted drop was recorded as failed and nothing was rebuilt.
    with closing(sqlite3.connect(db_path)) as connection:
        failed_row = connection.execute(
            "SELECT status, error FROM schema_migrations "
            "WHERE version = '2026-11-01-021-campaign-column-drop'"
        ).fetchone()
        open_trade_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('opentrades')").fetchall()
        }
    assert failed_row == ("failed", "simulated contract migration interruption")
    assert "campaign_id" in open_trade_columns

    resumed_database = Database()
    await resumed_database.init()
    await resumed_database.shutdown()
    await Tortoise.close_connections()

    assert attempts == 2
    with closing(sqlite3.connect(db_path)) as connection:
        applied_row = connection.execute(
            "SELECT status FROM schema_migrations "
            "WHERE version = '2026-11-01-021-campaign-column-drop'"
        ).fetchone()
        open_trade_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('opentrades')").fetchall()
        }
        open_trade = connection.execute(
            "SELECT symbol, deal_id, lifecycle_mode, exposure_state "
            "FROM opentrades WHERE symbol = 'BTC/USDC'"
        ).fetchone()
        closed_trade = connection.execute(
            "SELECT symbol, deal_id, close_reason FROM closedtrades "
            "WHERE symbol = 'ETH/USDC'"
        ).fetchone()
    assert applied_row == ("applied",)
    assert "campaign_id" not in open_trade_columns
    assert open_trade == (
        "BTC/USDC",
        "legacy-deal-btc-usdc",
        "classic_dca",
        "long_exposed",
    )
    assert closed_trade == (
        "ETH/USDC",
        "legacy-deal-eth-usdc",
        "take_profit",
    )


@pytest.mark.asyncio
async def test_open_trade_campaign_residue_aborts_startup(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live open-trade campaign residue blocks startup until it is cleared."""
    await Tortoise.close_connections()
    db_path = tmp_path / "legacy-v4.9.0.sqlite"
    fixture_sql = (FIXTURE_DIR / "legacy_v4_9_0.sql").read_text(encoding="utf-8")
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(fixture_sql)
        connection.execute(
            "UPDATE opentrades SET campaign_id = 'campaign-residue-1' "
            "WHERE symbol = 'BTC/USDC'"
        )
        connection.commit()

    monkeypatch.setenv("MOONWALKER_DB_URL", f"sqlite://{db_path}")

    blocked_database = Database()
    with pytest.raises(RuntimeError, match="restart.*resume safely") as excinfo:
        await blocked_database.init()
    await blocked_database.shutdown()
    await Tortoise.close_connections()

    cause_message = str(excinfo.value.__cause__)
    assert "opentrades" in cause_message
    assert "BTC/USDC" in cause_message
    assert "Moonwalker will not start until this is resolved" in cause_message
    assert "docs/operations.md" in cause_message

    # The failed drop rolled back: the residue and the columns are intact.
    with closing(sqlite3.connect(db_path)) as connection:
        open_trade_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('opentrades')").fetchall()
        }
        residue = connection.execute(
            "SELECT symbol, campaign_id FROM opentrades WHERE symbol = 'BTC/USDC'"
        ).fetchone()
        failed_row = connection.execute(
            "SELECT status FROM schema_migrations "
            "WHERE version = '2026-11-01-021-campaign-column-drop'"
        ).fetchone()
    assert "campaign_id" in open_trade_columns
    assert residue == ("BTC/USDC", "campaign-residue-1")
    assert failed_row == ("failed",)

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "UPDATE opentrades SET campaign_id = NULL WHERE symbol = 'BTC/USDC'"
        )
        connection.commit()

    resumed_database = Database()
    await resumed_database.init()
    await resumed_database.shutdown()
    await Tortoise.close_connections()

    with closing(sqlite3.connect(db_path)) as connection:
        open_trade_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('opentrades')").fetchall()
        }
        open_trade = connection.execute(
            "SELECT symbol, deal_id FROM opentrades WHERE symbol = 'BTC/USDC'"
        ).fetchone()
    assert "campaign_id" not in open_trade_columns
    assert open_trade is not None


@pytest.mark.asyncio
async def test_initial_entry_column_is_added_idempotently(_migration_database):
    """An existing accumulation installation gets a false default without data loss."""
    connection = Tortoise.get_connection("default")
    await connection.execute_script(
        "ALTER TABLE accumulation_opportunities DROP COLUMN is_initial_entry;"
    )
    database = Database()
    database.db_url = f"sqlite://{_migration_database}"
    await database._ensure_accumulation_initial_entry_schema()
    await database._ensure_accumulation_initial_entry_schema()
    _, columns = await connection.execute_query(
        "PRAGMA table_info('accumulation_opportunities')"
    )
    column = next(row for row in columns if row["name"] == "is_initial_entry")
    assert column["notnull"] == 1 and column["dflt_value"] == "0"


@pytest.mark.asyncio
async def test_startup_migrates_archive_column_when_old_migrations_already_applied(
    _migration_database,
):
    database = Database()
    database.db_url = f"sqlite://{_migration_database}"
    await database._run_schema_init_steps()
    # Reproduce an installation that completed every pre-archive migration.
    await SchemaMigration.filter(
        version="2026-10-23-015-accumulation-dust-archive"
    ).delete()
    connection = Tortoise.get_connection("default")
    await UnsellableTrades.create(symbol="BTC/USDC", amount=0.01, cost=1)
    await connection.execute_script(
        "ALTER TABLE unsellabletrades DROP COLUMN accumulation_inventory_json;"
    )
    await database._run_schema_init_steps()
    await database._run_schema_init_steps()
    row = await UnsellableTrades.get(symbol="BTC/USDC")
    assert row.amount == 0.01 and row.cost == 1
    assert row.accumulation_inventory_json is None
    ledger = await SchemaMigration.get(
        version="2026-10-23-015-accumulation-dust-archive"
    )
    assert ledger.status == "applied"


@pytest.mark.asyncio
async def test_contract_drop_rebuild_refuses_foreign_keys_and_triggers(
    tmp_path,
) -> None:
    """Value: protects=destructive-migration guard (the 021 table rebuild
    refuses foreign keys and triggers that reference dropped columns, while
    preserving triggers that reference only kept columns);
    fails_when=a rebuild silently drops FK/trigger constraints or partially
    rebuilds a table; why_new=the 4.9 fixture tables never carry foreign keys
    or triggers, so both refusal branches and the trigger-preservation path
    are unexercised; seam=none;
    no_claim=does not assert production table shapes."""
    await Tortoise.close_connections()
    db_path = tmp_path / "contract-drop-refusals.sqlite"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE fk_parent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NULL
            );
            CREATE TABLE fk_child (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NULL,
                parent_id INTEGER NOT NULL,
                FOREIGN KEY (parent_id) REFERENCES fk_parent(id)
            );
            INSERT INTO fk_parent (id, campaign_id) VALUES (1, 'parent-1');
            INSERT INTO fk_child (id, campaign_id, parent_id) VALUES (1, 'child-1', 1);
            CREATE TABLE triggered (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NULL
            );
            CREATE TRIGGER trg AFTER INSERT ON triggered BEGIN SELECT 1; END;
            CREATE TABLE triggered_dropped_ref (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NULL
            );
            CREATE TRIGGER trg_dropped_ref AFTER UPDATE OF campaign_id
            ON triggered_dropped_ref BEGIN SELECT 1; END;
            CREATE TABLE triggered_mixed_case_ref (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NULL
            );
            CREATE TRIGGER trg_mixed_case_ref AFTER UPDATE
            ON triggered_mixed_case_ref
            WHEN OLD.Campaign_Id IS NOT NULL BEGIN SELECT 1; END;
            """
        )
        connection.commit()

    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    conn = Tortoise.get_connection("default")
    try:
        with pytest.raises(RuntimeError, match="foreign keys"):
            await Database._rebuild_table_without_columns(
                conn, "fk_child", ("campaign_id",)
            )
        with pytest.raises(RuntimeError, match="trigger.*campaign_id"):
            await Database._rebuild_table_without_columns(
                conn, "triggered_dropped_ref", ("campaign_id",)
            )
        # SQLite identifiers are case-insensitive and trigger column
        # references are only checked at fire time, so a mixed-case
        # reference to a dropped column must refuse as well.
        with pytest.raises(RuntimeError, match="trigger.*campaign_id"):
            await Database._rebuild_table_without_columns(
                conn, "triggered_mixed_case_ref", ("campaign_id",)
            )
        # A trigger that references no dropped column survives the rebuild.
        await Database._rebuild_table_without_columns(
            conn, "triggered", ("campaign_id",)
        )
    finally:
        await Tortoise.close_connections()

    # The refusals left both refused tables untouched: no partial rebuild.
    with closing(sqlite3.connect(db_path)) as connection:
        child_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('fk_child')").fetchall()
        }
        dropped_ref_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('triggered_dropped_ref')"
            ).fetchall()
        }
        triggered_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('triggered')").fetchall()
        }
        triggered_triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = 'triggered'"
            ).fetchall()
        }
        child_rows = connection.execute(
            "SELECT id, campaign_id FROM fk_child"
        ).fetchall()
    assert "campaign_id" in child_columns
    assert "campaign_id" in dropped_ref_columns
    assert "campaign_id" not in triggered_columns
    assert "trg" in triggered_triggers
    assert child_rows == [(1, "child-1")]


@pytest.mark.asyncio
async def test_contract_drop_rebuild_preserves_incoming_foreign_key_references(
    tmp_path,
) -> None:
    """Value: protects=incoming-FK safety of the 021 table rebuild
    (a table referenced by other tables' foreign keys is rebuilt without
    firing their ON DELETE actions, so child rows keep their references);
    fails_when=the rebuild drops the parent while foreign-key enforcement is
    on and incoming references are silently SET NULL or the rebuild is
    refused by a RESTRICT child; why_new=the accumulation tables carry
    incoming keys into opentrades/placement_intents, which real installs
    always have, while the 4.9 fixture's child tables are empty; seam=none;
    no_claim=does not assert production table shapes."""
    await Tortoise.close_connections()
    db_path = tmp_path / "contract-drop-incoming-fk.sqlite"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE fk_parent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NULL
            );
            CREATE TABLE fk_child_setnull (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER NULL,
                FOREIGN KEY (parent_id) REFERENCES fk_parent(id)
                ON DELETE SET NULL
            );
            CREATE TABLE fk_child_restrict (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER NULL,
                FOREIGN KEY (parent_id) REFERENCES fk_parent(id)
                ON DELETE RESTRICT
            );
            INSERT INTO fk_parent (id, campaign_id) VALUES (1, 'parent-1');
            INSERT INTO fk_parent (id, campaign_id) VALUES (2, 'parent-2');
            INSERT INTO fk_child_setnull (parent_id) VALUES (1);
            INSERT INTO fk_child_restrict (parent_id) VALUES (2);
            """
        )
        connection.commit()

    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    conn = Tortoise.get_connection("default")
    try:
        await Database._rebuild_table_without_columns(
            conn, "fk_parent", ("campaign_id",)
        )
    finally:
        await Tortoise.close_connections()

    with closing(sqlite3.connect(db_path)) as connection:
        parent_ids = [row[0] for row in connection.execute("SELECT id FROM fk_parent")]
        setnull_refs = connection.execute(
            "SELECT parent_id FROM fk_child_setnull"
        ).fetchall()
        restrict_refs = connection.execute(
            "SELECT parent_id FROM fk_child_restrict"
        ).fetchall()
    assert parent_ids == [1, 2]
    # Both incoming references survive the rebuild untouched: with foreign
    # key enforcement on, the DROP would have SET NULL the first reference
    # and refused the rebuild because of the RESTRICT child.
    assert setnull_refs == [(1,)]
    assert restrict_refs == [(2,)]


@pytest.mark.asyncio
async def test_contract_drop_rebuild_preserves_autoincrement_high_water_mark(
    tmp_path,
) -> None:
    """Value: protects=AUTOINCREMENT high-water mark across the 021 table
    rebuild (the rebuild cannot reset sqlite_sequence and reuse deleted row
    IDs); fails_when=a rebuild leaves the sequence row missing so the next
    insert reuses the ID of a row deleted before the upgrade; why_new=the
    copy/drop/rename dance drops the sqlite_sequence row with the old
    table; seam=none; no_claim=does not assert production table shapes."""
    await Tortoise.close_connections()
    db_path = tmp_path / "contract-drop-sequence.sqlite"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE seq_parent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NULL
            );
            INSERT INTO seq_parent (id, campaign_id)
            VALUES (1, NULL), (2, NULL), (3, NULL);
            DELETE FROM seq_parent WHERE id = 3;
            """
        )
        connection.commit()

    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    conn = Tortoise.get_connection("default")
    try:
        await Database._rebuild_table_without_columns(
            conn, "seq_parent", ("campaign_id",)
        )
        await conn.execute_query("INSERT INTO seq_parent DEFAULT VALUES")
    finally:
        await Tortoise.close_connections()

    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute("SELECT id FROM seq_parent ORDER BY id").fetchall()
    # Without the preservation, the rebuilt table's max ID is 2 and the new
    # row would reuse the deleted ID 3.
    assert [row[0] for row in rows] == [1, 2, 4]


@pytest.mark.asyncio
async def test_contract_drop_rebuild_refuses_expression_and_partial_indexes(
    tmp_path,
) -> None:
    """Value: protects=explicit refusal of index shapes the 021 table
    rebuild cannot redeclare (expression indexes and partial WHERE
    predicates), instead of a late confusing failure mid-rebuild;
    fails_when=a rebuild silently drops an index predicate or aborts with
    an unactionable error after starting the copy; why_new=the rebuild
    redeclares indexes from column names alone; seam=none;
    no_claim=does not assert production table shapes."""
    await Tortoise.close_connections()
    db_path = tmp_path / "contract-drop-index-refusals.sqlite"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE expr_indexed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NULL,
                label TEXT NULL
            );
            CREATE INDEX idx_expr ON expr_indexed (length(label));
            CREATE TABLE partial_indexed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NULL,
                label TEXT NULL
            );
            CREATE INDEX idx_partial ON partial_indexed (label)
            WHERE label IS NOT NULL;
            """
        )
        connection.commit()

    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    conn = Tortoise.get_connection("default")
    try:
        with pytest.raises(RuntimeError, match="expression index"):
            await Database._rebuild_table_without_columns(
                conn, "expr_indexed", ("campaign_id",)
            )
        with pytest.raises(RuntimeError, match="partial"):
            await Database._rebuild_table_without_columns(
                conn, "partial_indexed", ("campaign_id",)
            )
    finally:
        await Tortoise.close_connections()

    # The refusals happened before the destructive DDL: both tables are
    # untouched, campaign column and indexes intact.
    with closing(sqlite3.connect(db_path)) as connection:
        for table in ("expr_indexed", "partial_indexed"):
            columns = {
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info('{table}')"
                ).fetchall()
            }
            indexes = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    f"WHERE type = 'index' AND tbl_name = '{table}'"
                ).fetchall()
            }
            assert "campaign_id" in columns
            assert ("idx_expr" if table == "expr_indexed" else "idx_partial") in indexes


@pytest.mark.asyncio
async def test_contract_drop_rebuild_rolls_back_when_ddl_fails_mid_dance(
    tmp_path,
) -> None:
    """Value: protects=atomicity of the 021 table rebuild (a statement
    failure or killed process mid-dance must roll the whole dance back and
    leave the original table intact); fails_when=the mutation phase
    autocommits each statement so a failure between DROP TABLE and the
    rename-back orphans every row in the side table and the next startup
    silently loses them; why_new=the FK pragma toggle requires the rebuild
    to run outside in_transaction(), so atomicity must come from an explicit
    BEGIN...COMMIT; seam=none; no_claim=does not assert production table
    shapes."""
    await Tortoise.close_connections()
    db_path = tmp_path / "contract-drop-rollback.sqlite"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE rollback_victim (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NULL,
                symbol TEXT NOT NULL
            );
            INSERT INTO rollback_victim (campaign_id, symbol)
            VALUES (NULL, 'A/USDT'), (NULL, 'B/USDT');
            """
        )
        connection.commit()

    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    conn = Tortoise.get_connection("default")
    original_execute = conn.execute_query

    async def failing_execute(query: str, *args: Any, **kwargs: Any):
        result = await original_execute(query, *args, **kwargs)
        # Simulate a failure (disk error, killed process) right after the
        # real drop commits its statement but before the rename-back.
        if "DROP TABLE" in query and "IF EXISTS" not in query:
            raise RuntimeError("simulated mid-ddl failure")
        return result

    conn.execute_query = failing_execute  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="simulated mid-ddl failure"):
            await Database._rebuild_table_without_columns(
                conn, "rollback_victim", ("campaign_id",)
            )
        # Foreign-key enforcement is restored even on the failure path.
        fk_state = (await conn.execute_query("PRAGMA foreign_keys"))[1]
        assert fk_state[0][0] == 1
    finally:
        await Tortoise.close_connections()

    with closing(sqlite3.connect(db_path)) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('rollback_victim')"
            ).fetchall()
        }
        rows = connection.execute(
            "SELECT symbol FROM rollback_victim ORDER BY id"
        ).fetchall()
        side_table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name = 'rollback_victim_campaign_drop_rebuild'"
        ).fetchall()
    # The rollback restored the original state: the table is intact with its
    # rows and campaign column, and the side table is gone.
    assert "campaign_id" in columns
    assert [row[0] for row in rows] == ["A/USDT", "B/USDT"]
    assert side_table == []


@pytest.mark.asyncio
async def test_contract_drop_refuses_orphaned_rebuild_side_table(tmp_path) -> None:
    """Value: protects=the rows of a table whose 021 rebuild crashed between
    DROP TABLE and the rename-back (a non-atomic build committed each
    statement, so a kill in that window strands the rows in the side table);
    fails_when=the next startup treats the missing table as a silent no-op,
    applies the migration and loses the rows; why_new=the fail-closed
    refusal turns an unrecoverable silent loss into an actionable error that
    names the side table; seam=none; no_claim=does not assert production
    table shapes."""
    await Tortoise.close_connections()
    db_path = tmp_path / "contract-drop-orphan.sqlite"
    with closing(sqlite3.connect(db_path)) as connection:
        # The orphan state: the side table holds the rows and the original
        # table is missing — exactly what a crash between DROP TABLE and the
        # rename-back leaves behind.
        connection.executescript(
            """
            CREATE TABLE orphan_victim_campaign_drop_rebuild (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL
            );
            INSERT INTO orphan_victim_campaign_drop_rebuild (symbol)
            VALUES ('A/USDT'), ('B/USDT');
            """
        )
        connection.commit()

    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    conn = Tortoise.get_connection("default")
    try:
        with pytest.raises(RuntimeError, match="orphan_victim_campaign_drop_rebuild"):
            await Database._rebuild_table_without_columns(
                conn, "orphan_victim", ("campaign_id",)
            )
    finally:
        await Tortoise.close_connections()

    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT symbol FROM orphan_victim_campaign_drop_rebuild ORDER BY id"
        ).fetchall()
    # The refusal left the stranded rows in place for manual recovery.
    assert [row[0] for row in rows] == ["A/USDT", "B/USDT"]
