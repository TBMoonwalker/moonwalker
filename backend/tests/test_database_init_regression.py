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
