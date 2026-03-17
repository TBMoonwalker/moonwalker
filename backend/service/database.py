"""Database lifecycle and SQLite resilience helpers."""

import os
import random
import sqlite3
from asyncio import sleep
from collections.abc import Awaitable, Callable
from typing import Any

import helper
import model
from tortoise import Tortoise
from tortoise.context import TortoiseContext
from tortoise.transactions import in_transaction

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

    async def _migrate_legacy_unsellable_open_trades(self) -> None:
        """Move unsellable legacy OpenTrades rows into UnsellableTrades."""
        legacy_rows = await model.OpenTrades.all().values()
        for open_trade in legacy_rows:
            unsellable_amount = float(open_trade.get("unsellable_amount") or 0.0)
            unsellable_reason = open_trade.get("unsellable_reason")
            if unsellable_amount <= 0 or not unsellable_reason:
                continue

            symbol = str(open_trade["symbol"])
            avg_price = float(open_trade.get("avg_price") or 0.0)
            current_price = float(open_trade.get("current_price") or 0.0)
            remaining_cost = (
                avg_price * unsellable_amount
                if avg_price > 0
                else float(open_trade.get("cost") or 0.0)
            )
            remaining_profit = current_price * unsellable_amount - remaining_cost
            remaining_profit_percent = (
                ((current_price - avg_price) / avg_price) * 100
                if avg_price > 0
                else float(open_trade.get("profit_percent") or 0.0)
            )

            async def _migrate_symbol() -> None:
                async with in_transaction() as conn:
                    await model.UnsellableTrades.create(
                        symbol=symbol,
                        so_count=int(open_trade.get("so_count") or 0),
                        profit=remaining_profit,
                        profit_percent=remaining_profit_percent,
                        amount=unsellable_amount,
                        cost=remaining_cost,
                        current_price=current_price,
                        avg_price=avg_price,
                        open_date=(
                            str(open_trade.get("open_date"))
                            if open_trade.get("open_date") is not None
                            else None
                        ),
                        unsellable_reason=str(unsellable_reason),
                        unsellable_min_notional=(
                            float(open_trade["unsellable_min_notional"])
                            if open_trade.get("unsellable_min_notional") is not None
                            else None
                        ),
                        unsellable_estimated_notional=(
                            float(open_trade["unsellable_estimated_notional"])
                            if open_trade.get("unsellable_estimated_notional")
                            is not None
                            else None
                        ),
                        unsellable_since=(
                            str(open_trade.get("unsellable_since"))
                            if open_trade.get("unsellable_since") is not None
                            else None
                        ),
                        using_db=conn,
                    )
                    await model.Trades.filter(symbol=symbol).using_db(conn).delete()
                    await model.OpenTrades.filter(symbol=symbol).using_db(conn).delete()

            await run_sqlite_write_with_retry(
                _migrate_symbol,
                f"migrating legacy unsellable trade for {symbol}",
            )
            logging.info("Migrated legacy unsellable open trade for %s", symbol)

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
            await self._ensure_indexes()
            await self._migrate_legacy_unsellable_open_trades()
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
