import sqlite3

import pytest
from service.database import (
    Database,
    _build_sqlite_corruption_message,
    _extract_added_column_names,
    _extract_corrupted_index_name,
    _plan_additive_column_statements,
)
from service.sqlite_timestamps import coerce_timestamp_like_to_ms


async def _noop(*_args, **_kwargs) -> None:
    return None


class _FakeConnection:
    def __init__(
        self,
        rows: list[tuple[str]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._rows = rows or []
        self._error = error

    async def execute_query(self, query: str) -> tuple[int, list[tuple[str]]]:
        assert query == "PRAGMA integrity_check"
        if self._error is not None:
            raise self._error
        return len(self._rows), self._rows


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        (
            [
                "row 1 missing from index idx_trades_deal_id_88bd51",
                "row 2 missing from index idx_trades_deal_id_88bd51",
            ],
            "idx_trades_deal_id_88bd51",
        ),
        (
            [
                "row 1 missing from index idx_trades_deal_id_88bd51",
                "row 2 missing from index idx_other",
            ],
            None,
        ),
        (["*** in database main ***\nPage 5 is never used"], None),
    ],
)
def test_extract_corrupted_index_name_detects_index_only_corruption(
    messages: list[str],
    expected: str | None,
) -> None:
    assert _extract_corrupted_index_name(messages) == expected


def test_plan_additive_column_statements_skips_existing_columns() -> None:
    statements = _plan_additive_column_statements(
        "opentrades",
        {"sold_amount", "unsellable_reason"},
        (
            ("sold_amount", "REAL NOT NULL DEFAULT 0.0"),
            ("sold_proceeds", "REAL NOT NULL DEFAULT 0.0"),
            ("unsellable_reason", "TEXT NULL"),
        ),
    )

    assert statements == [
        "ALTER TABLE opentrades ADD COLUMN sold_proceeds REAL NOT NULL DEFAULT 0.0;"
    ]
    assert _extract_added_column_names(statements) == ["sold_proceeds"]


def test_build_sqlite_corruption_message_prefers_reindex_guidance() -> None:
    message = _build_sqlite_corruption_message(
        "/tmp/broken.sqlite",
        [
            "row 1 missing from index idx_trades_deal_id_88bd51",
            "row 2 missing from index idx_trades_deal_id_88bd51",
        ],
    )

    assert "SQLite index corruption detected in /tmp/broken.sqlite" in message
    assert "REINDEX idx_trades_deal_id_88bd51; PRAGMA integrity_check;" in message


def test_build_sqlite_corruption_message_falls_back_to_generic_guidance() -> None:
    message = _build_sqlite_corruption_message(
        "/tmp/broken.sqlite",
        ["*** in database main ***\nPage 5 is never used"],
    )

    assert message == (
        "SQLite corruption detected in /tmp/broken.sqlite. "
        "Moonwalker cannot safely continue. "
        "Run `sqlite3 /tmp/broken.sqlite 'PRAGMA integrity_check;'` "
        "and restore from a known-good backup or recover the "
        "database before restarting."
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("120000", 120_000),
        ("1712345678", 1_712_345_678_000),
        ("1712345678901", 1_712_345_678_901),
    ],
)
def test_coerce_timestamp_like_to_ms_normalizes_numeric_string_ranges(
    value: str,
    expected: int,
) -> None:
    assert coerce_timestamp_like_to_ms(value) == expected


@pytest.mark.asyncio
async def test_run_sqlite_integrity_check_returns_empty_for_non_sqlite_db() -> None:
    database = Database()
    database.db_url = "postgres://moonwalker"

    assert await database._run_sqlite_integrity_check() == []


@pytest.mark.asyncio
async def test_run_sqlite_integrity_check_returns_trimmed_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database()
    database.db_url = "sqlite:///tmp/broken.sqlite"

    monkeypatch.setattr(
        "service.database.Tortoise.get_connection",
        lambda *_args, **_kwargs: _FakeConnection(
            rows=[
                (" row 1 missing from index idx_trades_deal_id_88bd51 ",),
                ("",),
                ("row 2 missing from index idx_trades_deal_id_88bd51",),
            ]
        ),
    )

    assert await database._run_sqlite_integrity_check() == [
        "row 1 missing from index idx_trades_deal_id_88bd51",
        "row 2 missing from index idx_trades_deal_id_88bd51",
    ]


@pytest.mark.asyncio
async def test_run_sqlite_integrity_check_returns_empty_when_query_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database()
    database.db_url = "sqlite:///tmp/broken.sqlite"

    monkeypatch.setattr(
        "service.database.Tortoise.get_connection",
        lambda *_args, **_kwargs: _FakeConnection(
            error=RuntimeError("integrity check unavailable")
        ),
    )

    assert await database._run_sqlite_integrity_check() == []


@pytest.mark.asyncio
async def test_database_init_surfaces_actionable_sqlite_corruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database()
    monkeypatch.setenv("MOONWALKER_DB_URL", "sqlite:///tmp/broken.sqlite")

    async def fake_tortoise_init(*_args, **_kwargs) -> object:
        return object()

    async def raise_malformed(*_args, **_kwargs) -> None:
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr("service.database.Tortoise.init", fake_tortoise_init)
    monkeypatch.setattr("service.database.Tortoise.generate_schemas", _noop)
    monkeypatch.setattr(Database, "_apply_sqlite_pragmas", _noop)
    monkeypatch.setattr(Database, "_ensure_open_trades_columns", _noop)
    monkeypatch.setattr(Database, "_ensure_trade_ledger_columns", _noop)
    monkeypatch.setattr(Database, "_ensure_upnl_history_columns", _noop)
    monkeypatch.setattr(Database, "_ensure_indexes", _noop)
    monkeypatch.setattr(Database, "_backfill_trade_ledger_rows", raise_malformed)
    monkeypatch.setattr(Database, "_backfill_trade_replay_candles", _noop)
    monkeypatch.setattr(Database, "_run_sqlite_integrity_check", _noop)

    with pytest.raises(
        RuntimeError, match="SQLite corruption detected in /tmp/broken.sqlite"
    ):
        await database.init()


@pytest.mark.asyncio
async def test_database_init_reraises_non_corruption_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database()
    monkeypatch.setenv("MOONWALKER_DB_URL", "sqlite:///tmp/healthy.sqlite")

    async def fake_tortoise_init(*_args, **_kwargs) -> object:
        return object()

    async def raise_generic(*_args, **_kwargs) -> None:
        raise RuntimeError("generic init failure")

    monkeypatch.setattr("service.database.Tortoise.init", fake_tortoise_init)
    monkeypatch.setattr("service.database.Tortoise.generate_schemas", _noop)
    monkeypatch.setattr(Database, "_apply_sqlite_pragmas", _noop)
    monkeypatch.setattr(Database, "_ensure_open_trades_columns", _noop)
    monkeypatch.setattr(Database, "_ensure_trade_ledger_columns", _noop)
    monkeypatch.setattr(Database, "_ensure_upnl_history_columns", _noop)
    monkeypatch.setattr(Database, "_ensure_indexes", _noop)
    monkeypatch.setattr(Database, "_backfill_trade_ledger_rows", raise_generic)
    monkeypatch.setattr(Database, "_backfill_trade_replay_candles", _noop)

    with pytest.raises(RuntimeError, match="generic init failure"):
        await database.init()


@pytest.mark.asyncio
async def test_database_init_surfaces_index_rebuild_guidance_for_index_only_corruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database()
    monkeypatch.setenv("MOONWALKER_DB_URL", "sqlite:///tmp/broken.sqlite")

    async def fake_tortoise_init(*_args, **_kwargs) -> object:
        return object()

    async def raise_malformed(*_args, **_kwargs) -> None:
        raise sqlite3.DatabaseError("database disk image is malformed")

    async def fake_integrity_check(*_args, **_kwargs) -> list[str]:
        return [
            "row 1 missing from index idx_trades_deal_id_88bd51",
            "row 2 missing from index idx_trades_deal_id_88bd51",
        ]

    monkeypatch.setattr("service.database.Tortoise.init", fake_tortoise_init)
    monkeypatch.setattr("service.database.Tortoise.generate_schemas", _noop)
    monkeypatch.setattr(Database, "_apply_sqlite_pragmas", _noop)
    monkeypatch.setattr(Database, "_ensure_open_trades_columns", _noop)
    monkeypatch.setattr(Database, "_ensure_trade_ledger_columns", _noop)
    monkeypatch.setattr(Database, "_ensure_upnl_history_columns", _noop)
    monkeypatch.setattr(Database, "_ensure_indexes", _noop)
    monkeypatch.setattr(Database, "_backfill_trade_ledger_rows", raise_malformed)
    monkeypatch.setattr(Database, "_backfill_trade_replay_candles", _noop)
    monkeypatch.setattr(Database, "_run_sqlite_integrity_check", fake_integrity_check)

    with pytest.raises(
        RuntimeError,
        match=(
            "SQLite index corruption detected in /tmp/broken.sqlite "
            r"\(idx_trades_deal_id_88bd51\)"
        ),
    ) as exc_info:
        await database.init()

    assert "REINDEX idx_trades_deal_id_88bd51; PRAGMA integrity_check;" in str(
        exc_info.value
    )


@pytest.mark.asyncio
async def test_database_init_runs_schema_steps_before_trade_ledger_backfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database()
    calls: list[str] = []
    monkeypatch.setenv("MOONWALKER_DB_URL", "sqlite:///tmp/healthy.sqlite")

    async def fake_tortoise_init(*_args, **_kwargs) -> object:
        calls.append("tortoise_init")
        return object()

    async def fake_generate_schemas(*_args, **_kwargs) -> None:
        calls.append("generate_schemas")

    def _record(name: str):
        async def _step(*_args, **_kwargs) -> None:
            calls.append(name)

        return _step

    monkeypatch.setattr("service.database.Tortoise.init", fake_tortoise_init)
    monkeypatch.setattr(
        "service.database.Tortoise.generate_schemas", fake_generate_schemas
    )
    monkeypatch.setattr(Database, "_apply_sqlite_pragmas", _record("apply_pragmas"))
    monkeypatch.setattr(
        Database, "_ensure_open_trades_columns", _record("ensure_open_trades_columns")
    )
    monkeypatch.setattr(
        Database, "_ensure_trade_ledger_columns", _record("ensure_trade_ledger_columns")
    )
    monkeypatch.setattr(
        Database, "_ensure_upnl_history_columns", _record("ensure_upnl_history_columns")
    )
    monkeypatch.setattr(Database, "_ensure_indexes", _record("ensure_indexes"))
    monkeypatch.setattr(
        Database, "_backfill_trade_ledger_rows", _record("backfill_trade_ledger_rows")
    )

    await database.init()

    assert calls == [
        "tortoise_init",
        "apply_pragmas",
        "generate_schemas",
        "ensure_open_trades_columns",
        "ensure_trade_ledger_columns",
        "ensure_upnl_history_columns",
        "ensure_indexes",
        "backfill_trade_ledger_rows",
    ]


@pytest.mark.asyncio
async def test_background_replay_backfill_runs_after_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database()
    database.db_url = "sqlite:///tmp/healthy.sqlite"
    calls: list[str] = []

    async def fake_backfill(*_args, **_kwargs) -> None:
        calls.append("backfill_trade_replay_candles")

    monkeypatch.setattr(Database, "_backfill_trade_replay_candles", fake_backfill)

    await database.backfill_trade_replay_candles_if_needed()

    assert calls == ["backfill_trade_replay_candles"]


@pytest.mark.asyncio
async def test_background_replay_backfill_does_not_raise_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database()
    database.db_url = "sqlite:///tmp/healthy.sqlite"

    async def raise_failure(*_args, **_kwargs) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(Database, "_backfill_trade_replay_candles", raise_failure)

    await database.backfill_trade_replay_candles_if_needed()
