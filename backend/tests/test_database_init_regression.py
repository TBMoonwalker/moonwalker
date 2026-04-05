import sqlite3

import pytest
from service.database import Database


async def _noop(*_args, **_kwargs) -> None:
    return None


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

    with pytest.raises(
        RuntimeError, match="SQLite corruption detected in /tmp/broken.sqlite"
    ):
        await database.init()
