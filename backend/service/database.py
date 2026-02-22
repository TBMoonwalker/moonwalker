"""Database lifecycle and SQLite resilience helpers."""

import os
import random
import sqlite3
from asyncio import sleep
from collections.abc import Awaitable, Callable
from typing import Any

import helper
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
            ("trades", "idx_trades_symbol_baseorder", ("symbol", "baseorder")),
            (
                "trades",
                "idx_trades_symbol_safety_base",
                ("symbol", "safetyorder", "baseorder"),
            ),
            ("closedtrades", "idx_closedtrades_close_date", ("close_date",)),
            ("upnl_history", "idx_upnl_history_timestamp", ("timestamp",)),
            ("token_listings", "idx_token_listings_symbol", ("symbol",)),
        )
        existing_signatures: set[tuple[str, tuple[str, ...]]] = set()
        tables = {table for table, _, _ in desired_indexes}

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
            await self._ensure_indexes()
            logging.info("Database initialized successfully")
        except Exception as exc:  # noqa: BLE001 - Catch all exceptions during init
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
