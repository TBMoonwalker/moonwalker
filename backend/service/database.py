"""Database lifecycle and SQLite resilience helpers."""

import os
import random
import sqlite3
from asyncio import sleep
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import helper
import model
from service.replay_candles import archive_replay_candles_for_deal
from tortoise import Tortoise
from tortoise.context import TortoiseContext

logging = helper.LoggerFactory.get_logger("logs/database.log", "database")

SQLITE_LOCK_RETRIES = 5
SQLITE_RETRY_BASE_DELAY_SECONDS = 0.02
SQLITE_RETRY_MAX_DELAY_SECONDS = 0.2


def _is_sqlite_lock_error(exc: Exception) -> bool:
    """Return True if exception indicates SQLite lock contention."""
    if isinstance(exc, sqlite3.OperationalError):
        return True
    text = str(exc).lower()
    return "database is locked" in text or "database table is locked" in text


def _is_sqlite_malformed_error(exc: Exception) -> bool:
    """Return True if exception indicates SQLite file or index corruption."""
    if not isinstance(exc, sqlite3.DatabaseError):
        return False
    return "database disk image is malformed" in str(exc).lower()


def _resolve_sqlite_db_path(db_url: str) -> str:
    """Return a readable filesystem path for a SQLite connection URL."""
    return (
        db_url.removeprefix("sqlite://") if db_url.startswith("sqlite://") else db_url
    )


async def run_sqlite_write_with_retry(
    operation: Callable[[], Awaitable[Any]],
    operation_name: str,
    retries: int = SQLITE_LOCK_RETRIES,
) -> Any:
    """Run an async write operation with lock-retry for SQLite."""
    attempt = 0
    while True:
        try:
            return await operation()
        except Exception as exc:  # noqa: BLE001 - Retry only for lock errors.
            if attempt >= retries or not _is_sqlite_lock_error(exc):
                raise
            delay = min(
                SQLITE_RETRY_BASE_DELAY_SECONDS * (2**attempt)
                + random.uniform(0, SQLITE_RETRY_BASE_DELAY_SECONDS),
                SQLITE_RETRY_MAX_DELAY_SECONDS,
            )
            logging.warning(
                "SQLite lock during %s (attempt %s/%s). Retrying in %.3fs",
                operation_name,
                attempt + 1,
                retries,
                delay,
            )
            await sleep(delay)
            attempt += 1


async def optimize_sqlite_connection(db_url: str | None = None) -> None:
    """Run PRAGMA optimize when the active backend is SQLite."""
    active_db_url = db_url or os.getenv(
        "MOONWALKER_DB_URL", "sqlite://db/trades.sqlite"
    )
    if not active_db_url.startswith("sqlite://"):
        return
    connection = Tortoise.get_connection("default")
    await connection.execute_query("PRAGMA optimize")


class Database:
    """Database connection management class for Tortoise ORM.

    Handles initialization, connection management, and shutdown of the database
    connection pool for the application.
    """

    def __init__(self) -> None:
        """Initialize the Database instance.

        Sets the database file name and initializes logging.

        Attributes:
            db_file: Name of the SQLite database file.
        """
        self.db_file = "trades.sqlite"
        self.db_url = ""
        self._ctx: TortoiseContext | None = None
        logging.info("Database instance initialized")

    async def _apply_sqlite_pragmas(self) -> None:
        """Apply SQLite concurrency and cache tuning pragmas."""
        if not self.db_url.startswith("sqlite://"):
            return

        pragma_statements = """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA busy_timeout=10000;
        PRAGMA wal_autocheckpoint=2000;
        PRAGMA temp_store=MEMORY;
        PRAGMA mmap_size=268435456;
        PRAGMA cache_size=-64000;
        """
        connection = Tortoise.get_connection("default")
        await connection.execute_script(pragma_statements)
        logging.info("Applied SQLite pragmas for WAL/concurrency tuning")

    async def _ensure_indexes(self) -> None:
        """Create performance-critical indexes for existing databases.

        This only creates indexes that are not already present by column
        signature to avoid duplicate indexes with different names.
        """
        if not self.db_url.startswith("sqlite://"):
            return

        connection = Tortoise.get_connection("default")
        desired_indexes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
            ("tickers", "idx_tickers_symbol_timestamp", ("symbol", "timestamp")),
            ("tickers", "idx_tickers_timestamp", ("timestamp",)),
            ("trades", "idx_trades_symbol", ("symbol",)),
            ("trades", "idx_trades_deal_id_timestamp", ("deal_id", "timestamp")),
            ("trades", "idx_trades_symbol_baseorder", ("symbol", "baseorder")),
            (
                "trades",
                "idx_trades_symbol_safety_base",
                ("symbol", "safetyorder", "baseorder"),
            ),
            ("closedtrades", "idx_closedtrades_close_date", ("close_date",)),
            (
                "tradeexecutions",
                "idx_tradeexecutions_deal_time",
                ("deal_id", "timestamp"),
            ),
            (
                "tradeexecutions",
                "idx_tradeexecutions_symbol_time",
                ("symbol", "timestamp"),
            ),
            ("tradeexecutions", "idx_tradeexecutions_side_role", ("side", "role")),
            (
                "tradereplaycandles",
                "idx_tradereplaycandles_deal_time",
                ("deal_id", "timestamp"),
            ),
            (
                "tradereplaycandles",
                "idx_tradereplaycandles_symbol_time",
                ("symbol", "timestamp"),
            ),
            (
                "unsellabletrades",
                "idx_unsellabletrades_symbol",
                ("symbol",),
            ),
            (
                "unsellabletrades",
                "idx_unsellabletrades_since",
                ("unsellable_since",),
            ),
            ("upnl_history", "idx_upnl_history_timestamp", ("timestamp",)),
            ("token_listings", "idx_token_listings_symbol", ("symbol",)),
        )
        desired_unique_indexes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
            ("opentrades", "uidx_opentrades_deal_id", ("deal_id",)),
            ("closedtrades", "uidx_closedtrades_deal_id", ("deal_id",)),
            ("unsellabletrades", "uidx_unsellabletrades_deal_id", ("deal_id",)),
        )
        existing_signatures: set[tuple[str, tuple[str, ...]]] = set()
        existing_unique_signatures: set[tuple[str, tuple[str, ...]]] = set()
        tables = {table for table, _, _ in [*desired_indexes, *desired_unique_indexes]}

        for table in tables:
            _, indexes = await connection.execute_query(f"PRAGMA index_list('{table}')")
            for index in indexes:
                index_name = index["name"]
                _, index_cols = await connection.execute_query(
                    f"PRAGMA index_info('{index_name}')"
                )
                columns = tuple(
                    row["name"]
                    for row in sorted(index_cols, key=lambda row: row["seqno"])
                )
                if columns:
                    existing_signatures.add((table, columns))
                if columns and bool(index["unique"]):
                    existing_unique_signatures.add((table, columns))

        create_statements = [
            (
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON {table} ({', '.join(columns)});"
            )
            for table, index_name, columns in desired_indexes
            if (table, columns) not in existing_signatures
        ]
        if create_statements:
            await connection.execute_script("\n".join(create_statements))

        unique_statements = [
            (
                f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
                f"ON {table} ({', '.join(columns)});"
            )
            for table, index_name, columns in desired_unique_indexes
            if (table, columns) not in existing_unique_signatures
        ]
        if unique_statements:
            await connection.execute_script("\n".join(unique_statements))

    async def _ensure_trade_ledger_columns(self) -> None:
        """Ensure additive deal-ledger columns exist on existing SQLite databases."""
        if not self.db_url.startswith("sqlite://"):
            return

        connection = Tortoise.get_connection("default")
        table_columns = {
            "trades": (("deal_id", "TEXT NULL"),),
            "opentrades": (
                ("deal_id", "TEXT NULL"),
                ("execution_history_complete", "INTEGER NOT NULL DEFAULT 1"),
            ),
            "closedtrades": (
                ("deal_id", "TEXT NULL"),
                ("execution_history_complete", "INTEGER NOT NULL DEFAULT 0"),
            ),
            "unsellabletrades": (
                ("deal_id", "TEXT NULL"),
                ("execution_history_complete", "INTEGER NOT NULL DEFAULT 0"),
            ),
        }

        alter_statements: list[str] = []
        for table_name, column_specs in table_columns.items():
            _, columns = await connection.execute_query(
                f"PRAGMA table_info('{table_name}')"
            )
            existing = {row["name"] for row in columns}
            for column_name, column_definition in column_specs:
                if column_name in existing:
                    continue
                alter_statements.append(
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN {column_name} {column_definition};"
                )

        if alter_statements:
            await connection.execute_script("\n".join(alter_statements))
            logging.info("Added missing deal-ledger columns.")

    @staticmethod
    def _resolve_trade_execution_role(trade_row: dict[str, Any]) -> str:
        """Return the replay role for a historical trade row."""
        if bool(trade_row.get("baseorder")):
            return "base_order"
        if str(trade_row.get("orderid") or "").startswith("manual-add-"):
            return "manual_buy"
        if bool(trade_row.get("safetyorder")):
            return "safety_order"
        return "buy"

    async def _backfill_trade_ledger_rows(self) -> None:
        """Backfill deal ids and execution rows for currently open deals."""
        if not self.db_url.startswith("sqlite://"):
            return

        open_rows = await model.OpenTrades.all().values(
            "symbol",
            "deal_id",
            "sold_amount",
            "execution_history_complete",
        )
        for open_row in open_rows:
            symbol = str(open_row.get("symbol") or "").strip()
            if not symbol:
                continue

            deal_id = str(open_row.get("deal_id") or uuid4())
            has_legacy_partial = float(open_row.get("sold_amount") or 0.0) > 0
            execution_history_complete = (
                bool(open_row.get("execution_history_complete", True))
                and not has_legacy_partial
            )

            await model.OpenTrades.filter(symbol=symbol).update(
                deal_id=deal_id,
                execution_history_complete=execution_history_complete,
            )
            await model.Trades.filter(symbol=symbol).update(deal_id=deal_id)

            existing_executions = await model.TradeExecutions.filter(
                deal_id=deal_id,
            ).values("timestamp", "order_id", "role")
            existing_signatures = {
                (
                    str(execution.get("timestamp") or ""),
                    str(execution.get("order_id") or ""),
                    str(execution.get("role") or ""),
                )
                for execution in existing_executions
            }
            trade_rows = (
                await model.Trades.filter(symbol=symbol)
                .order_by(
                    "timestamp",
                    "id",
                )
                .values()
            )
            for trade_row in trade_rows:
                role = self._resolve_trade_execution_role(trade_row)
                signature = (
                    str(trade_row.get("timestamp") or ""),
                    str(trade_row.get("orderid") or ""),
                    role,
                )
                if signature in existing_signatures:
                    continue

                await model.TradeExecutions.create(
                    deal_id=deal_id,
                    symbol=str(trade_row.get("symbol") or symbol),
                    side=str(trade_row.get("side") or "buy"),
                    role=role,
                    timestamp=str(trade_row.get("timestamp") or ""),
                    price=float(trade_row.get("price") or 0.0),
                    amount=float(trade_row.get("amount") or 0.0),
                    ordersize=float(trade_row.get("ordersize") or 0.0),
                    fee=float(trade_row.get("fee") or 0.0),
                    order_id=(
                        str(trade_row.get("orderid"))
                        if trade_row.get("orderid") is not None
                        else None
                    ),
                    order_type=(
                        str(trade_row.get("ordertype"))
                        if trade_row.get("ordertype") is not None
                        else None
                    ),
                    order_count=trade_row.get("order_count"),
                    so_percentage=(
                        float(trade_row["so_percentage"])
                        if trade_row.get("so_percentage") is not None
                        else None
                    ),
                )
                existing_signatures.add(signature)

    async def _backfill_trade_replay_candles(self) -> None:
        """Backfill per-deal replay candles for existing closed trades."""
        if not self.db_url.startswith("sqlite://"):
            return

        closed_rows = await model.ClosedTrades.exclude(deal_id=None).values(
            "deal_id",
            "symbol",
            "open_date",
            "close_date",
        )
        for closed_row in closed_rows:
            deal_id = str(closed_row.get("deal_id") or "").strip()
            symbol = str(closed_row.get("symbol") or "").strip()
            if not deal_id or not symbol:
                continue
            await archive_replay_candles_for_deal(
                deal_id,
                symbol,
                open_date=closed_row.get("open_date"),
                close_date=closed_row.get("close_date"),
            )

    async def _ensure_open_trades_columns(self) -> None:
        """Ensure additive OpenTrades columns exist on existing SQLite databases."""
        if not self.db_url.startswith("sqlite://"):
            return

        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query("PRAGMA table_info('opentrades')")
        existing = {row["name"] for row in columns}
        alter_statements = []
        if "sold_amount" not in existing:
            alter_statements.append(
                "ALTER TABLE opentrades ADD COLUMN sold_amount REAL NOT NULL DEFAULT 0.0;"
            )
        if "sold_proceeds" not in existing:
            alter_statements.append(
                "ALTER TABLE opentrades ADD COLUMN sold_proceeds REAL NOT NULL DEFAULT 0.0;"
            )
        if "unsellable_amount" not in existing:
            alter_statements.append(
                "ALTER TABLE opentrades ADD COLUMN unsellable_amount REAL NOT NULL DEFAULT 0.0;"
            )
        if "unsellable_reason" not in existing:
            alter_statements.append(
                "ALTER TABLE opentrades ADD COLUMN unsellable_reason TEXT NULL;"
            )
        if "unsellable_min_notional" not in existing:
            alter_statements.append(
                "ALTER TABLE opentrades ADD COLUMN unsellable_min_notional REAL NULL;"
            )
        if "unsellable_estimated_notional" not in existing:
            alter_statements.append(
                "ALTER TABLE opentrades ADD COLUMN unsellable_estimated_notional REAL NULL;"
            )
        if "unsellable_since" not in existing:
            alter_statements.append(
                "ALTER TABLE opentrades ADD COLUMN unsellable_since TEXT NULL;"
            )
        if "unsellable_notice_sent" not in existing:
            alter_statements.append(
                "ALTER TABLE opentrades ADD COLUMN unsellable_notice_sent INTEGER NOT NULL DEFAULT 0;"
            )
        if alter_statements:
            await connection.execute_script("\n".join(alter_statements))
            logging.info(
                "Added missing OpenTrades columns: %s",
                ", ".join(
                    statement.split("ADD COLUMN", 1)[1].split()[0].strip()
                    for statement in alter_statements
                ),
            )

    async def _ensure_upnl_history_columns(self) -> None:
        """Ensure additive UpnlHistory columns exist on existing SQLite databases."""
        if not self.db_url.startswith("sqlite://"):
            return

        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query("PRAGMA table_info('upnl_history')")
        existing = {row["name"] for row in columns}
        alter_statements = []
        if "funds_locked" not in existing:
            alter_statements.append(
                "ALTER TABLE upnl_history "
                "ADD COLUMN funds_locked REAL NOT NULL DEFAULT 0.0;"
            )
        if alter_statements:
            await connection.execute_script("\n".join(alter_statements))
            logging.info(
                "Added missing UpnlHistory columns: %s",
                ", ".join(
                    statement.split("ADD COLUMN", 1)[1].split()[0].strip()
                    for statement in alter_statements
                ),
            )

    async def optimize_sqlite(self) -> None:
        """Run SQLite planner/index maintenance."""
        await optimize_sqlite_connection(self.db_url)

    async def init(self) -> None:
        """Initialize the database connection and generate schemas.

        Sets up the Tortoise ORM connection and creates all database tables
        based on the model definitions.

        Raises:
            Exception: If database initialization fails.
        """
        try:
            db_url = os.getenv("MOONWALKER_DB_URL", f"sqlite://db/{self.db_file}")
            self.db_url = db_url
            self._ctx = await Tortoise.init(
                db_url=db_url,
                modules={"models": ["model"]},
                _enable_global_fallback=True,
            )
            await self._apply_sqlite_pragmas()
            # Generate the schema
            await Tortoise.generate_schemas()
            await self._ensure_open_trades_columns()
            await self._ensure_trade_ledger_columns()
            await self._ensure_upnl_history_columns()
            await self._ensure_indexes()
            await self._backfill_trade_ledger_rows()
            await self._backfill_trade_replay_candles()
            logging.info("Database initialized successfully")
        except Exception as exc:  # noqa: BLE001 - Catch all exceptions during init
            if _is_sqlite_malformed_error(exc):
                db_path = _resolve_sqlite_db_path(self.db_url or db_url)
                message = (
                    f"SQLite corruption detected in {db_path}. "
                    "Moonwalker cannot safely continue. "
                    f"Run `sqlite3 {db_path} 'PRAGMA integrity_check;'` and "
                    "restore from a known-good backup or recover the database "
                    "before restarting."
                )
                logging.error(message, exc_info=True)
                raise RuntimeError(message) from exc
            logging.error("Failed to initialize database: %s", exc, exc_info=True)
            raise

    async def run_with_context(
        self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
    ) -> Any:
        """Run an async callable with globally initialized Tortoise context."""
        if self._ctx is None:
            raise RuntimeError("Tortoise context is not initialized")
        return await func(*args, **kwargs)

    async def shutdown(self) -> None:
        """Close all database connections.

        Properly shuts down the Tortoise ORM connection pool and releases
        all database resources.

        Raises:
            Exception: If connection shutdown fails.
        """
        try:
            if self._ctx is not None:
                await self._ctx.close_connections()
                self._ctx = None
            else:
                await Tortoise.close_connections()
            logging.info("Database connections closed successfully")
        except Exception as exc:  # noqa: BLE001 - Catch all exceptions during shutdown
            logging.error(
                "Failed to close database connections: %s", exc, exc_info=True
            )
            raise
