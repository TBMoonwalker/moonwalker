import sqlite3

import pytest
from service.database import Database, _extract_corrupted_index_name


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
