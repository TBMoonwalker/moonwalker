"""Database lifecycle and SQLite resilience helpers."""

import asyncio
import os
import random
import re
import sqlite3
from asyncio import sleep
from collections.abc import Awaitable, Callable, Iterable
from typing import Any
from uuid import uuid4

import helper
import model
from service.msv import MINIMUM_SUPPORTED_VERSION, preflight_msv
from service.replay_candles import archive_replay_candles_for_deal
from service.schema_migrations import (
    CONTRACT_DROP_COMPATIBILITY,
    MigrationDefinition,
    bootstrap_sqlite_migration_ledger,
    run_schema_migrations,
)
from tortoise import Tortoise
from tortoise.context import TortoiseContext
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger("logs/database.log", "database")

SQLITE_LOCK_RETRIES = 5
SQLITE_RETRY_BASE_DELAY_SECONDS = 0.02
SQLITE_RETRY_MAX_DELAY_SECONDS = 0.2
_SQLITE_INDEX_CORRUPTION_PATTERNS = (
    re.compile(r"row \d+ missing from index (?P<index>\S+)"),
    re.compile(r"rowid \d+ missing from index (?P<index>\S+)"),
    re.compile(r"wrong # of entries in index (?P<index>\S+)"),
)
ColumnSpec = tuple[str, str]

# Tables and columns removed by the first contract migration (021).  The
# dead opentrades columns were sidestep-era campaign state that no live code
# writes; the campaign_id columns carried pre-4.9 campaign linkage that is
# dropped with its rows' identity falling back to deal_id || id.
_LEGACY_CAMPAIGN_REBUILDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "opentrades",
        (
            "campaign_id",
            "reserved_reentry_quote",
            "waiting_reference_price",
            "waiting_reference_amount",
            "waiting_reference_quote",
            "virtual_waiting_profit",
            "virtual_waiting_profit_percent",
            "last_transition_at",
        ),
    ),
    ("trades", ("campaign_id",)),
    ("closedtrades", ("campaign_id",)),
    ("tradeexecutions", ("campaign_id",)),
    ("placement_intents", ("campaign_id",)),
)


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


def _extract_corrupted_index_name(messages: list[str]) -> str | None:
    """Return the damaged SQLite index name when integrity_check is index-only."""
    index_names = _extract_corrupted_index_names(messages)
    return index_names[0] if index_names and len(index_names) == 1 else None


def _extract_corrupted_index_names(messages: list[str]) -> list[str] | None:
    """Return damaged SQLite index names when integrity_check is index-only."""
    if not messages:
        return None

    index_names: set[str] = set()
    for message in messages:
        normalized = str(message).strip()
        if not normalized or normalized.lower() == "ok":
            return None

        matched = False
        for pattern in _SQLITE_INDEX_CORRUPTION_PATTERNS:
            result = pattern.fullmatch(normalized)
            if result:
                index_names.add(result.group("index"))
                matched = True
                break
        if not matched:
            return None

    return sorted(index_names) if index_names else None


def _integrity_check_is_clean(messages: list[str]) -> bool:
    """Return True when integrity_check reported a healthy database."""
    if not messages:
        return False
    return all(str(message).strip().lower() == "ok" for message in messages)


def _quote_sqlite_pragma_string(value: str) -> str:
    """Return a SQL string literal for SQLite PRAGMA arguments."""
    return "'" + value.replace("'", "''") + "'"


def _plan_additive_column_statements(
    table_name: str,
    existing_columns: set[str],
    column_specs: tuple[ColumnSpec, ...],
) -> list[str]:
    """Return ALTER TABLE statements for additive columns that are still missing."""
    statements: list[str] = []
    for column_name, column_definition in column_specs:
        if column_name in existing_columns:
            continue
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition};"
        )
    return statements


def _extract_added_column_names(statements: list[str]) -> list[str]:
    """Return the added column names from ALTER TABLE ADD COLUMN statements."""
    return [
        statement.split("ADD COLUMN", 1)[1].split()[0].strip()
        for statement in statements
    ]


def _build_sqlite_corruption_message(
    db_path: str,
    integrity_messages: list[str],
) -> str:
    """Return operator guidance for detected SQLite corruption."""
    corrupted_index_names = _extract_corrupted_index_names(integrity_messages)
    if corrupted_index_names and len(corrupted_index_names) > 1:
        return (
            f"SQLite index corruption detected in {db_path} "
            f"({', '.join(corrupted_index_names)}). Moonwalker cannot safely continue. "
            f"First try `sqlite3 {db_path} 'REINDEX; PRAGMA integrity_check;'`. "
            "If integrity_check still reports errors, restore from "
            "a known-good backup or recover the database before restarting."
        )

    corrupted_index_name = _extract_corrupted_index_name(integrity_messages)
    if corrupted_index_name:
        return (
            f"SQLite index corruption detected in {db_path} "
            f"({corrupted_index_name}). Moonwalker cannot safely continue. "
            f"First try `sqlite3 {db_path} 'REINDEX "
            f"{corrupted_index_name}; PRAGMA integrity_check;'`. "
            "If integrity_check still reports errors, restore from "
            "a known-good backup or recover the database before restarting."
        )

    return (
        f"SQLite corruption detected in {db_path}. "
        "Moonwalker cannot safely continue. "
        f"Run `sqlite3 {db_path} 'PRAGMA integrity_check;'` "
        "and restore from a known-good backup or recover the "
        "database before restarting."
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
            (
                "autopilot_memory_events",
                "idx_autopilot_memory_events_created_at",
                ("created_at",),
            ),
            (
                "autopilot_memory_events",
                "idx_autopilot_memory_events_symbol_created_at",
                ("symbol", "created_at"),
            ),
            (
                "autopilot_symbol_memory",
                "idx_autopilot_symbol_memory_direction_score",
                ("trust_direction", "trust_score"),
            ),
            (
                "autopilot_symbol_memory",
                "idx_autopilot_symbol_memory_updated_at",
                ("updated_at",),
            ),
            (
                "ai_trust_predictions",
                "idx_ai_trust_predictions_created_at",
                ("created_at",),
            ),
            (
                "ai_trust_predictions",
                "idx_ai_trust_predictions_deal_id",
                ("deal_id",),
            ),
            (
                "ai_trust_predictions",
                "idx_ai_trust_predictions_symbol_created_at",
                ("symbol", "created_at"),
            ),
            (
                "ai_trust_predictions",
                "idx_ai_trust_predictions_status_provider",
                ("status", "provider_status"),
            ),
            (
                "ai_trust_predictions",
                "idx_ai_trust_predictions_outcome_bad",
                ("outcome_status", "bad_entry"),
            ),
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
            ("closedtrades", "idx_closedtrades_close_reason", ("close_reason",)),
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
                "opentrades",
                "idx_opentrades_exposure_state_symbol",
                ("exposure_state", "symbol"),
            ),
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
                "placement_intents",
                "idx_placement_intents_state_symbol",
                ("state", "symbol"),
            ),
            (
                "placement_intents",
                "idx_placement_intents_exchange_order_id",
                ("exchange_order_id",),
            ),
            (
                "placement_intents",
                "idx_placement_intents_deal_id",
                ("deal_id",),
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
            (
                "strategy_versions",
                "idx_strategy_versions_slug_version",
                ("strategy_slug", "version"),
            ),
            (
                "strategy_graph_state",
                "idx_strategy_graph_state_lookup",
                ("strategy_slug", "state_key", "symbol", "timeframe"),
            ),
            ("upnl_history", "idx_upnl_history_timestamp", ("timestamp",)),
            ("token_listings", "idx_token_listings_symbol", ("symbol",)),
        )
        desired_unique_indexes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
            ("opentrades", "uidx_opentrades_deal_id", ("deal_id",)),
            ("closedtrades", "uidx_closedtrades_deal_id", ("deal_id",)),
            ("unsellabletrades", "uidx_unsellabletrades_deal_id", ("deal_id",)),
            ("strategy_definitions", "uidx_strategy_definitions_slug", ("slug",)),
            (
                "placement_intents",
                "uidx_placement_intents_operation_id",
                ("operation_id",),
            ),
            (
                "placement_intents",
                "uidx_placement_intents_client_order_id",
                ("client_order_id",),
            ),
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
            "tradeexecutions": (
                ("strategy_slug", "TEXT NULL"),
                ("strategy_version", "INTEGER NULL"),
            ),
            "opentrades": (
                ("deal_id", "TEXT NULL"),
                ("execution_history_complete", "INTEGER NOT NULL DEFAULT 1"),
                (
                    "lifecycle_mode",
                    "TEXT NOT NULL DEFAULT 'classic_dca'",
                ),
                (
                    "exposure_state",
                    "TEXT NOT NULL DEFAULT 'long_exposed'",
                ),
            ),
            "closedtrades": (
                ("deal_id", "TEXT NULL"),
                ("close_reason", "TEXT NULL"),
                ("execution_history_complete", "INTEGER NOT NULL DEFAULT 0"),
            ),
            "unsellabletrades": (
                ("accumulation_inventory_json", "TEXT NULL"),
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
            alter_statements.extend(
                _plan_additive_column_statements(
                    table_name,
                    existing,
                    column_specs,
                )
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

        open_rows = await model.OpenTrades.all().values("symbol", "deal_id")
        for open_row in open_rows:
            symbol = str(open_row.get("symbol") or "").strip()
            if not symbol:
                continue

            deal_id = str(open_row.get("deal_id") or uuid4())
            await model.OpenTrades.filter(symbol=symbol).update(deal_id=deal_id)
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
        """Backfill or repair per-deal replay candles for existing closed trades."""
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
                allow_missing_archive_exchange_repair=True,
                allow_live_snapshot_exchange_repair=True,
            )

    async def _ensure_open_trades_columns(self) -> None:
        """Ensure additive OpenTrades columns exist on existing SQLite databases."""
        if not self.db_url.startswith("sqlite://"):
            return

        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query("PRAGMA table_info('opentrades')")
        existing = {row["name"] for row in columns}
        alter_statements = _plan_additive_column_statements(
            "opentrades",
            existing,
            (
                ("sold_amount", "REAL NOT NULL DEFAULT 0.0"),
                ("sold_proceeds", "REAL NOT NULL DEFAULT 0.0"),
                ("unsellable_amount", "REAL NOT NULL DEFAULT 0.0"),
                ("unsellable_reason", "TEXT NULL"),
                ("unsellable_min_notional", "REAL NULL"),
                ("unsellable_estimated_notional", "REAL NULL"),
                ("unsellable_since", "TEXT NULL"),
                ("unsellable_notice_sent", "INTEGER NOT NULL DEFAULT 0"),
                ("tp_limit_order_id", "TEXT NULL"),
                ("tp_limit_order_price", "REAL NULL"),
                ("tp_limit_order_amount", "REAL NULL"),
                ("tp_limit_order_armed_at", "TEXT NULL"),
                (
                    "dca_sizing_mode",
                    "TEXT NOT NULL DEFAULT 'legacy_factors'",
                ),
                ("dca_policy_json", "TEXT NULL"),
                ("dca_reference_price", "REAL NOT NULL DEFAULT 0.0"),
                (
                    "dca_reference_atr_percent",
                    "REAL NOT NULL DEFAULT 0.0",
                ),
                ("dca_next_trigger_price", "REAL NOT NULL DEFAULT 0.0"),
                ("dca_last_decision_json", "TEXT NULL"),
                ("automation_paused", "INTEGER NOT NULL DEFAULT 0"),
                ("automation_paused_at", "TEXT NULL"),
            ),
        )
        if alter_statements:
            await connection.execute_script("\n".join(alter_statements))
            logging.info(
                "Added missing OpenTrades columns: %s",
                ", ".join(_extract_added_column_names(alter_statements)),
            )

    async def _ensure_upnl_history_columns(self) -> None:
        """Ensure additive UpnlHistory columns exist on existing SQLite databases."""
        if not self.db_url.startswith("sqlite://"):
            return

        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query("PRAGMA table_info('upnl_history')")
        existing = {row["name"] for row in columns}
        alter_statements = _plan_additive_column_statements(
            "upnl_history",
            existing,
            (("funds_locked", "REAL NOT NULL DEFAULT 0.0"),),
        )
        if alter_statements:
            await connection.execute_script("\n".join(alter_statements))
            logging.info(
                "Added missing UpnlHistory columns: %s",
                ", ".join(_extract_added_column_names(alter_statements)),
            )

    async def _ensure_ai_trust_columns(self) -> None:
        """Ensure additive AI evaluation identity exists on legacy databases."""
        if not self.db_url.startswith("sqlite://"):
            return

        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query(
            "PRAGMA table_info('ai_trust_predictions')"
        )
        existing = {row["name"] for row in columns}
        alter_statements = _plan_additive_column_statements(
            "ai_trust_predictions",
            existing,
            (("evaluation_id", "TEXT NULL"),),
        )
        if alter_statements:
            await connection.execute_script("\n".join(alter_statements))
        await connection.execute_script(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uid_ai_trust_evaluation_id "
            "ON ai_trust_predictions (evaluation_id);"
        )

    async def _run_sqlite_quick_check(self) -> list[str]:
        """Return SQLite quick_check messages for the active database."""
        if not self.db_url.startswith("sqlite://"):
            return []

        try:
            connection = Tortoise.get_connection("default")
            _, rows = await connection.execute_query("PRAGMA quick_check")
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            logging.warning(
                "Failed to run SQLite quick_check during corruption diagnosis: %s",
                exc,
                exc_info=True,
            )
            return []

        return [str(row[0]).strip() for row in rows if str(row[0]).strip()]

    async def _run_sqlite_integrity_check(
        self,
        table_names: Iterable[str] | None = None,
    ) -> list[str]:
        """Return SQLite integrity_check messages for the active database."""
        if not self.db_url.startswith("sqlite://"):
            return []

        try:
            connection = Tortoise.get_connection("default")
            if table_names is None:
                _, rows = await connection.execute_query("PRAGMA integrity_check")
                return [str(row[0]).strip() for row in rows if str(row[0]).strip()]

            messages: list[str] = []
            for table_name in table_names:
                quoted_table = _quote_sqlite_pragma_string(table_name)
                _, rows = await connection.execute_query(
                    f"PRAGMA integrity_check({quoted_table})"
                )
                messages.extend(
                    str(row[0]).strip() for row in rows if str(row[0]).strip()
                )
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            logging.warning(
                "Failed to run SQLite integrity_check during corruption diagnosis: %s",
                exc,
                exc_info=True,
            )
            return []

        return messages

    async def _reindex_sqlite_database(self) -> None:
        """Rebuild all indexes for the active SQLite database."""
        if not self.db_url.startswith("sqlite://"):
            return

        connection = Tortoise.get_connection("default")
        await connection.execute_query("REINDEX")

    async def _repair_index_only_corruption_if_needed(self) -> None:
        """Repair index-only SQLite corruption before runtime services start."""
        quick_messages = await self._run_sqlite_quick_check()
        if not quick_messages:
            return

        integrity_messages = quick_messages
        if _integrity_check_is_clean(quick_messages):
            integrity_messages = await self._run_sqlite_integrity_check()
        if not integrity_messages:
            return
        if _integrity_check_is_clean(integrity_messages):
            return

        corrupted_index_names = _extract_corrupted_index_names(integrity_messages)
        if corrupted_index_names is None:
            db_path = _resolve_sqlite_db_path(self.db_url)
            message = _build_sqlite_corruption_message(db_path, integrity_messages)
            logging.error(message)
            raise RuntimeError(message)

        logging.warning(
            "SQLite index-only corruption detected in %s for indexes: %s. "
            "Attempting automatic REINDEX before startup continues.",
            _resolve_sqlite_db_path(self.db_url),
            ", ".join(corrupted_index_names),
        )
        await self._reindex_sqlite_database()
        repaired_messages = await self._run_sqlite_quick_check()
        if _integrity_check_is_clean(repaired_messages):
            repaired_messages = await self._run_sqlite_integrity_check()
        if _integrity_check_is_clean(repaired_messages):
            logging.warning(
                "SQLite index corruption repaired successfully via REINDEX."
            )
            return

        db_path = _resolve_sqlite_db_path(self.db_url)
        message = _build_sqlite_corruption_message(db_path, repaired_messages)
        logging.error(message)
        raise RuntimeError(message)

    async def _run_schema_init_steps(self) -> None:
        """Run ordered additive schema migrations for existing databases."""
        await run_schema_migrations(
            (
                MigrationDefinition(
                    version="2026-07-28-001-open-trades-expand",
                    phase="schema",
                    description="Add backward-compatible open-trade runtime columns.",
                    apply=self._ensure_open_trades_columns,
                ),
                MigrationDefinition(
                    version="2026-07-28-003-trade-ledger-expand",
                    phase="schema",
                    description="Add deal and campaign execution-ledger identity.",
                    apply=self._ensure_trade_ledger_columns,
                ),
                MigrationDefinition(
                    version="2026-07-28-004-upnl-expand",
                    phase="schema",
                    description="Add persisted locked-funds history.",
                    apply=self._ensure_upnl_history_columns,
                ),
                MigrationDefinition(
                    version="2026-07-28-005-ai-trust-expand",
                    phase="schema",
                    description="Add stable AI evaluation identity.",
                    apply=self._ensure_ai_trust_columns,
                ),
                MigrationDefinition(
                    version="2026-07-28-006-indexes",
                    phase="schema",
                    description="Create current additive and unique indexes.",
                    apply=self._ensure_indexes,
                ),
                MigrationDefinition(
                    version="2026-08-02-008-strategy-history-expand",
                    phase="schema",
                    description="Add immutable strategy identity to trade executions.",
                    apply=self._ensure_strategy_history_schema,
                ),
                MigrationDefinition(
                    version="2026-10-17-009-accumulation-foundation",
                    phase="schema",
                    description="Add accumulation identities and exact inventory totals.",
                    apply=self._ensure_accumulation_schema,
                ),
                MigrationDefinition(
                    version="2026-10-17-010-accumulation-lifecycle",
                    phase="schema",
                    description="Add durable accumulation operator command journal.",
                    apply=self._ensure_accumulation_lifecycle_schema,
                ),
                MigrationDefinition(
                    version="2026-10-17-011-accumulation-accounting",
                    phase="schema",
                    description="Add cumulative accumulation fill checkpoints.",
                    apply=self._ensure_accumulation_accounting_schema,
                ),
                MigrationDefinition(
                    version="2026-10-18-012-accumulation-signal-peak",
                    phase="schema",
                    description="Freeze accumulation signal peak for sizing retries.",
                    apply=self._ensure_accumulation_strategy_schema,
                ),
                MigrationDefinition(
                    version="2026-10-21-013-accumulation-return-totals",
                    phase="schema",
                    description="Add rebuildable exact return totals and indexed evidence coverage.",
                    apply=self._ensure_accumulation_return_schema,
                ),
                MigrationDefinition(
                    version="2026-10-22-014-accumulation-initial-entry",
                    phase="schema",
                    description="Identify ASAP base orders independently of strategy signals.",
                    apply=self._ensure_accumulation_initial_entry_schema,
                ),
                MigrationDefinition(
                    version="2026-10-23-015-accumulation-dust-archive",
                    phase="schema",
                    description="Add exact inventory evidence to unsellable accumulation dust.",
                    apply=self._ensure_trade_ledger_columns,
                ),
                MigrationDefinition(
                    version="2026-10-26-016-trade-cost-provenance",
                    phase="schema",
                    description="Distinguish fee-inclusive acquisition costs from legacy fee estimates.",
                    apply=self._ensure_trade_cost_provenance,
                ),
                MigrationDefinition(
                    version="2026-10-27-017-closed-trade-mode",
                    phase="schema",
                    description="Add nullable closed-trade lifecycle attribution.",
                    apply=self._ensure_closed_trade_mode,
                ),
                MigrationDefinition(
                    version="2026-10-27-018-accumulation-history-revision",
                    phase="schema",
                    description="Track changes to mutable accumulation activity records.",
                    apply=self._ensure_accumulation_history_revision,
                ),
                MigrationDefinition(
                    version="2026-10-27-019-accumulation-contributions",
                    phase="schema",
                    description="Add rebuildable lifetime contribution totals.",
                    apply=self._ensure_accumulation_contributions,
                ),
                MigrationDefinition(
                    version="2026-10-28-020-manual-stop-valuation",
                    phase="schema",
                    description="Separate unsold market valuation from realized returns.",
                    apply=self._ensure_manual_stop_valuation,
                ),
                MigrationDefinition(
                    version="2026-11-01-021-campaign-column-drop",
                    phase="schema",
                    description="Drop dormant campaign columns from the trade tables.",
                    apply=self._drop_legacy_campaign_columns,
                    compatibility=CONTRACT_DROP_COMPATIBILITY,
                ),
            )
        )

    async def _drop_legacy_campaign_columns(self) -> None:
        """Drop the dead campaign columns once every install is at the MSV floor.

        First contract (destructive) migration. Rebuilds the affected tables
        without the legacy campaign columns and keeps every other field of
        every row. Aborts startup when a live open trade still carries
        campaign residue: the drop would silently unlink it from its position.
        See docs/operations.md, "Campaign residue recovery".

        The residue check runs in its own transaction and the rebuilds run
        after it commits: the accumulation tables carry incoming foreign keys
        into opentrades/placement_intents, and the rebuild must toggle
        ``PRAGMA foreign_keys`` around the drop, which SQLite only allows
        outside a transaction. Every rebuild restores its rows with their
        original IDs, so incoming references stay valid. Each rebuild's
        mutation phase is one explicit transaction, so an error or a killed
        process leaves the original table intact; a table whose columns are
        already gone is a no-op, and a missing table alongside its
        side table (a crash in an older, non-atomic build) is refused with
        an actionable error instead of a silent no-op.
        """
        if not self.db_url.startswith("sqlite://"):
            return
        async with in_transaction():
            await self._assert_no_open_trade_campaign_residue(
                Tortoise.get_connection("default")
            )
        connection = Tortoise.get_connection("default")
        for table, drop_columns in _LEGACY_CAMPAIGN_REBUILDS:
            await self._rebuild_table_without_columns(connection, table, drop_columns)

    @staticmethod
    async def _assert_no_open_trade_campaign_residue(conn: Any) -> None:
        """Fail closed on live open trades that still reference a campaign."""
        _, columns = await conn.execute_query("PRAGMA table_info(opentrades)")
        if not any(row["name"] == "campaign_id" for row in columns):
            return
        _, residue_rows = await conn.execute_query(
            "SELECT symbol FROM opentrades WHERE campaign_id IS NOT NULL"
        )
        if not residue_rows:
            return
        symbols = ", ".join(sorted(str(row["symbol"]) for row in residue_rows))
        raise RuntimeError(
            "Startup aborted: the opentrades table has "
            f"{len(residue_rows)} open trade row(s) with legacy campaign "
            f"residue (symbols: {symbols}). Moonwalker will not start until "
            "this is resolved. Review the open position(s) on the exchange, "
            "then clear the campaign_id value(s); see docs/operations.md, "
            '"Campaign residue recovery".'
        )

    @staticmethod
    async def _assert_no_orphaned_campaign_rebuild_tables(db_url: str) -> None:
        """Fail closed on a crashed campaign-drop rebuild before schemas run.

        A non-atomic rebuild that crashed between ``DROP TABLE`` and the
        rename-back leaves the original table missing while its rows sit in
        the ``<table>_campaign_drop_rebuild`` side table.
        ``Tortoise.generate_schemas`` would recreate the original table
        empty before the migration runs, and the rebuild would then no-op
        silently, losing the stranded rows. This check therefore runs before
        schema generation.
        """
        if not db_url.startswith("sqlite://"):
            return
        conn = Tortoise.get_connection("default")
        for table, _drop_columns in _LEGACY_CAMPAIGN_REBUILDS:
            _, original_columns = await conn.execute_query(
                f"PRAGMA table_info({table})"
            )
            if original_columns:
                continue
            side_table = f"{table}_campaign_drop_rebuild"
            _, side_columns = await conn.execute_query(
                f"PRAGMA table_info({side_table})"
            )
            if side_columns:
                raise RuntimeError(
                    f"Startup aborted: {table} is missing, but an "
                    f"interrupted campaign-drop rebuild left its rows in "
                    f"{side_table}. Rename {side_table} back to {table} "
                    "(or restore from a backup), then start Moonwalker "
                    "again."
                )

    @staticmethod
    async def _rebuild_table_without_columns(
        conn: Any,
        table: str,
        drop_columns: tuple[str, ...],
    ) -> None:
        """Rebuild one SQLite table without the given columns.

        The table is recreated with every kept column, its rows are copied
        over, and user-created indexes that reference only kept columns are
        recreated. Unique constraints are re-declared as table constraints.
        Triggers that reference only kept columns are dropped with the old
        table and recreated unchanged, because the rebuild renames back to
        the original table name. The mutation phase runs with foreign-key
        enforcement temporarily disabled so incoming foreign keys (held by
        the accumulation tables) keep their references: the rows are
        restored with their original IDs. The AUTOINCREMENT high-water mark
        is preserved across the rebuild. The mutation phase (drop, copy,
        rename, index, trigger and sequence restore) runs inside one explicit
        BEGIN...COMMIT transaction, so on failure the original table is left
        intact. A missing original table alongside its side table (a crash
        in an older, non-atomic rebuild that committed each statement) is
        refused rather than silently no-opped: the rows are stranded in the
        side table and must be recovered first. A table with foreign keys,
        or a trigger that references a dropped column, is refused rather
        than rebuilt; expression and partial indexes are refused as well
        because the rebuild cannot redeclare them.
        """
        _, columns = await conn.execute_query(f"PRAGMA table_info({table})")
        if not columns:
            side_table = f"{table}_campaign_drop_rebuild"
            _, side_columns = await conn.execute_query(
                f"PRAGMA table_info({side_table})"
            )
            if side_columns:
                raise RuntimeError(
                    f"Startup aborted: {table} is missing, but an "
                    f"interrupted campaign-drop rebuild left its rows in "
                    f"{side_table}. Rename {side_table} back to {table} "
                    "(or restore from a backup), then start Moonwalker "
                    "again."
                )
            return
        to_drop = {
            name for name in drop_columns if any(row["name"] == name for row in columns)
        }
        if not to_drop:
            return

        _, foreign_keys = await conn.execute_query(f"PRAGMA foreign_key_list({table})")
        if foreign_keys:
            raise RuntimeError(
                f"Cannot rebuild {table}: unexpected foreign keys found."
            )
        _, triggers = await conn.execute_query(
            "SELECT name, sql FROM sqlite_master "
            f"WHERE type = 'trigger' AND tbl_name = '{table}'"
        )
        for trigger in triggers:
            trigger_sql = trigger["sql"] or ""
            for column in to_drop:
                # SQLite identifiers are case-insensitive and trigger
                # column references are not validated at CREATE TRIGGER
                # time, so a mixed-case reference must refuse too.
                if re.search(rf"\b{re.escape(column)}\b", trigger_sql, re.IGNORECASE):
                    raise RuntimeError(
                        f"Cannot rebuild {table}: trigger "
                        f"{trigger['name']} references dropped column {column}."
                    )

        kept_columns = [row for row in columns if row["name"] not in to_drop]
        autoincrement = False
        _, create_rows = await conn.execute_query(
            f"SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{table}'"
        )
        if create_rows:
            autoincrement = "AUTOINCREMENT" in (create_rows[0]["sql"] or "").upper()

        column_defs: list[str] = []
        for row in kept_columns:
            column_name = row["name"]
            if row["pk"]:
                column_defs.append(
                    f"{column_name} {row['type'] or 'INTEGER'} PRIMARY KEY"
                    + (" AUTOINCREMENT" if autoincrement else "")
                )
                continue
            definition = f"{column_name} {row['type'] or 'TEXT'}"
            if row["notnull"]:
                definition += " NOT NULL"
            if row["dflt_value"] is not None:
                definition += f" DEFAULT {row['dflt_value']}"
            column_defs.append(definition)

        unique_constraints: list[tuple[str, ...]] = []
        recreated_indexes: list[tuple[str, bool, tuple[str, ...]]] = []
        _, index_rows = await conn.execute_query(f"PRAGMA index_list({table})")
        for index in index_rows:
            index_name = index["name"]
            if not index_name:
                continue
            _, index_cols = await conn.execute_query(
                f'PRAGMA index_info("{index_name}")'
            )
            index_columns = tuple(
                row["name"] for row in sorted(index_cols, key=lambda row: row["seqno"])
            )
            if any(col is None for col in index_columns):
                raise RuntimeError(
                    f"Cannot rebuild {table}: index {index_name} is an "
                    "expression index; the rebuild cannot redeclare it."
                )
            if not index_columns or any(col in to_drop for col in index_columns):
                continue
            if index["origin"] == "pk":
                continue
            _, index_sql_rows = await conn.execute_query(
                "SELECT sql FROM sqlite_master "
                f"WHERE type = 'index' AND name = '{index_name}'"
            )
            if (
                index_sql_rows
                and index_sql_rows[0]["sql"]
                and re.search(r"\bWHERE\b", index_sql_rows[0]["sql"], re.IGNORECASE)
            ):
                raise RuntimeError(
                    f"Cannot rebuild {table}: index {index_name} is a partial "
                    "(WHERE) index; the rebuild cannot redeclare its predicate."
                )
            if bool(index["unique"]) and str(index_name).startswith(
                "sqlite_autoindex_"
            ):
                unique_constraints.append(index_columns)
            else:
                recreated_indexes.append(
                    (index_name, bool(index["unique"]), index_columns)
                )

        new_table = f"{table}_campaign_drop_rebuild"
        table_sql = ", ".join(
            [
                *column_defs,
                *(f"UNIQUE ({', '.join(cols)})" for cols in unique_constraints),
            ]
        )
        # The rebuild must run with foreign-key enforcement off: SQLite fires
        # the ON DELETE actions of incoming foreign keys (SET NULL, RESTRICT)
        # when a parent table is dropped. The rows are restored with their
        # original IDs, so those references stay valid and must be left
        # untouched. The high-water mark is captured before the drop so the
        # rebuild cannot reset it and reuse deleted row IDs.
        fk_state = (await conn.execute_query("PRAGMA foreign_keys"))[1]
        fk_on = bool(fk_state) and bool(fk_state[0][0])
        seq_value = None
        if autoincrement:
            seq_rows = (
                await conn.execute_query(
                    f"SELECT seq FROM sqlite_sequence WHERE name = '{table}'"
                )
            )[1]
            seq_value = seq_rows[0]["seq"] if seq_rows else None
        if fk_on:
            await conn.execute_query("PRAGMA foreign_keys=OFF")
        try:
            # An explicit transaction makes the dance atomic: the connection
            # is autocommit (isolation_level=None), so without it a failure
            # or a killed process between `DROP TABLE` and the rename-back
            # would commit the drop and strand every row in the side table.
            # On failure the rollback restores the original state.
            await conn.execute_query("BEGIN")
            try:
                await conn.execute_query(f"DROP TABLE IF EXISTS {new_table}")
                await conn.execute_query(f"CREATE TABLE {new_table} ({table_sql})")
                kept_names = ", ".join(row["name"] for row in kept_columns)
                await conn.execute_query(
                    f"INSERT INTO {new_table} ({kept_names}) "
                    f"SELECT {kept_names} FROM {table}"
                )
                await conn.execute_query(f"DROP TABLE {table}")
                await conn.execute_query(f"ALTER TABLE {new_table} RENAME TO {table}")
                for index_name, unique, index_columns in recreated_indexes:
                    unique_sql = "UNIQUE " if unique else ""
                    await conn.execute_query(
                        f"CREATE {unique_sql}INDEX {index_name} "
                        f"ON {table} ({', '.join(index_columns)})"
                    )
                for trigger in triggers:
                    await conn.execute_query(trigger["sql"])
                if autoincrement:
                    pk_name = next(row["name"] for row in kept_columns if row["pk"])
                    max_rows = (
                        await conn.execute_query(
                            f"SELECT MAX({pk_name}) AS m FROM {table}"
                        )
                    )[1]
                    preserved = (
                        seq_value if seq_value is not None else (max_rows[0]["m"] or 0)
                    )
                    remaining = (
                        await conn.execute_query(
                            f"SELECT seq FROM sqlite_sequence WHERE name = '{table}'"
                        )
                    )[1]
                    if remaining:
                        await conn.execute_query(
                            f"UPDATE sqlite_sequence SET seq = {preserved} "
                            f"WHERE name = '{table}'"
                        )
                    elif preserved:
                        await conn.execute_query(
                            f"INSERT INTO sqlite_sequence (name, seq) "
                            f"VALUES ('{table}', {preserved})"
                        )
                await conn.execute_query("COMMIT")
            except Exception:
                await conn.execute_query("ROLLBACK")
                raise
        finally:
            if fk_on:
                await conn.execute_query("PRAGMA foreign_keys=ON")

    async def _ensure_manual_stop_valuation(self) -> None:
        """Add optional unsold valuation fields without rewriting past closes."""
        if not self.db_url.startswith("sqlite://"):
            return
        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query("PRAGMA table_info('closedtrades')")
        statements = _plan_additive_column_statements(
            "closedtrades",
            {row["name"] for row in columns},
            (("valuation_quantity", "REAL NULL"), ("valuation_price", "REAL NULL")),
        )
        if statements:
            await connection.execute_script("\n".join(statements))

        _, snapshot_columns = await connection.execute_query(
            "PRAGMA table_info('upnl_history')"
        )
        snapshot_statements = _plan_additive_column_statements(
            "upnl_history",
            {row["name"] for row in snapshot_columns},
            (("performance_verified", "INTEGER NOT NULL DEFAULT 1"),),
        )
        if snapshot_statements:
            await connection.execute_script("\n".join(snapshot_statements))
        await connection.execute_query(
            "UPDATE upnl_history SET performance_verified = 0 WHERE EXISTS "
            "(SELECT 1 FROM closedtrades WHERE close_reason = 'manual_stop' "
            "AND valuation_quantity IS NULL)"
        )

    async def _ensure_accumulation_contributions(self) -> None:
        """Mark existing contribution caches for a verified historical rebuild."""
        if not self.db_url.startswith("sqlite://"):
            return
        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query(
            "PRAGMA table_info('accumulation_return_totals')"
        )
        statements = _plan_additive_column_statements(
            "accumulation_return_totals",
            {row["name"] for row in columns},
            (("contributed_quote", "TEXT NULL"),),
        )
        if statements:
            await connection.execute_script("\n".join(statements))

    async def _ensure_accumulation_history_revision(self) -> None:
        """Track activity mutations so paginated snapshots fail closed on changes."""
        if not self.db_url.startswith("sqlite://"):
            return
        connection = Tortoise.get_connection("default")
        await connection.execute_script("""
            CREATE TABLE IF NOT EXISTS accumulation_history_revision (
                id INTEGER PRIMARY KEY CHECK (id = 1), revision INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO accumulation_history_revision VALUES (1, 0);
            CREATE INDEX IF NOT EXISTS idx_accumulation_checkpoint_activity
              ON accumulation_fill_checkpoints (updated_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_accumulation_operation_activity
              ON accumulation_lifecycle_operations (updated_at DESC, id DESC);
        """)
        for table in (
            "accumulation_fill_checkpoints",
            "accumulation_lifecycle_operations",
        ):
            for operation in ("INSERT", "UPDATE", "DELETE"):
                name = f"history_revision_{table}_{operation.lower()}"
                await connection.execute_script(
                    f"CREATE TRIGGER IF NOT EXISTS {name} AFTER {operation} ON {table} "
                    "BEGIN UPDATE accumulation_history_revision "
                    "SET revision = revision + 1 WHERE id = 1; END;"
                )
        for table, columns in (
            ("accumulation_activations", "symbol, account_scope"),
            ("placement_intents", "symbol, side"),
        ):
            changed = " OR ".join(
                f"OLD.{column.strip()} IS NOT NEW.{column.strip()}"
                for column in columns.split(",")
            )
            await connection.execute_script(
                f"CREATE TRIGGER IF NOT EXISTS history_revision_{table}_identity "
                f"AFTER UPDATE OF {columns} ON {table} WHEN {changed} "
                "BEGIN UPDATE accumulation_history_revision "
                "SET revision = revision + 1 WHERE id = 1; END;"
            )

    async def _ensure_closed_trade_mode(self) -> None:
        """Keep legacy closures unattributed unless evidence proves their mode."""
        if not self.db_url.startswith("sqlite://"):
            return
        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query("PRAGMA table_info('closedtrades')")
        statements = _plan_additive_column_statements(
            "closedtrades",
            {row["name"] for row in columns},
            (("lifecycle_mode", "TEXT NULL"),),
        )
        if statements:
            await connection.execute_script("\n".join(statements))
        await connection.execute_query(
            "CREATE INDEX IF NOT EXISTS idx_accumulation_checkpoint_deal_id "
            "ON accumulation_fill_checkpoints (deal_id)"
        )
        # A deal identity and matching activation and placement symbols are
        # durable accumulation evidence. Never infer DCA from missing evidence.
        await connection.execute_query("""
            UPDATE closedtrades AS closed SET lifecycle_mode = 'accumulation'
            WHERE closed.lifecycle_mode IS NULL AND closed.deal_id IS NOT NULL
              AND EXISTS (
                SELECT 1 FROM accumulation_fill_checkpoints AS checkpoint
                JOIN accumulation_activations AS activation
                  ON activation.id = checkpoint.activation_id
                JOIN placement_intents AS placement
                  ON placement.id = checkpoint.placement_id
                WHERE checkpoint.deal_id = closed.deal_id
                  AND activation.symbol = closed.symbol
                  AND placement.symbol = closed.symbol
              )
              AND NOT EXISTS (
                SELECT 1 FROM accumulation_fill_checkpoints AS checkpoint
                JOIN accumulation_activations AS activation
                  ON activation.id = checkpoint.activation_id
                JOIN placement_intents AS placement
                  ON placement.id = checkpoint.placement_id
                WHERE checkpoint.deal_id = closed.deal_id
                  AND (activation.symbol != closed.symbol
                       OR placement.symbol != closed.symbol)
              )
        """)

    async def _ensure_trade_cost_provenance(self) -> None:
        """Add provenance without rewriting quantities, costs or historical fees."""
        if not self.db_url.startswith("sqlite://"):
            return
        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query("PRAGMA table_info('trades')")
        statements = _plan_additive_column_statements(
            "trades",
            {row["name"] for row in columns},
            (("cost_includes_fees", "INT NULL"),),
        )
        if statements:
            await connection.execute_script("\n".join(statements))

    async def _ensure_accumulation_initial_entry_schema(self) -> None:
        """Mark only newly prepared ASAP entries; historical buys stay unchanged."""
        if not self.db_url.startswith("sqlite://"):
            return
        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query(
            "PRAGMA table_info('accumulation_opportunities')"
        )
        statements = _plan_additive_column_statements(
            "accumulation_opportunities",
            {row["name"] for row in columns},
            (("is_initial_entry", "INT NOT NULL DEFAULT 0"),),
        )
        if statements:
            await connection.execute_script("\n".join(statements))

    async def _ensure_accumulation_return_schema(self) -> None:
        """Verify derived tables and index bounded routine coverage checks."""
        await model.AccumulationReturnTotals.all().limit(1).values("activation_id")
        await model.AccumulationReturnDay.all().limit(1).values("id")
        if self.db_url.startswith("sqlite://"):
            await Tortoise.get_connection("default").execute_script(
                "CREATE INDEX IF NOT EXISTS idx_accumulation_fee_coverage ON accumulation_fill_checkpoints (activation_id, fees_complete, terminal); CREATE INDEX IF NOT EXISTS idx_accumulation_terminal_coverage ON accumulation_fill_checkpoints (activation_id, terminal); CREATE INDEX IF NOT EXISTS idx_accumulation_latest_inventory ON accumulation_fill_checkpoints (activation_id, updated_at DESC, id DESC);"
            )

    async def _ensure_accumulation_lifecycle_schema(self) -> None:
        """Verify the command journal created by safe ORM schema generation."""
        await model.AccumulationLifecycleOperation.all().limit(1).values("id")

    async def _ensure_accumulation_accounting_schema(self) -> None:
        """Verify exact fill checkpoints created by safe ORM schema generation."""
        await model.AccumulationFillCheckpoint.all().limit(1).values("id")

    async def _ensure_accumulation_strategy_schema(self) -> None:
        """Leave pre-evaluator opportunities without an invented signal peak."""
        if not self.db_url.startswith("sqlite://"):
            return
        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query(
            "PRAGMA table_info('accumulation_opportunities')"
        )
        statements = _plan_additive_column_statements(
            "accumulation_opportunities",
            {row["name"] for row in columns},
            (("signal_peak", "TEXT NULL"),),
        )
        if statements:
            await connection.execute_script("\n".join(statements))

    async def _ensure_accumulation_schema(self) -> None:
        """Expand legacy holdings without converting or estimating their balances.

        New accumulation tables and constraints are created by safe ORM schema
        generation before this migration. Existing holdings retain their mode;
        NULL exact totals deliberately distinguish legacy/unknown accounting.
        """
        if not self.db_url.startswith("sqlite://"):
            return
        connection = Tortoise.get_connection("default")
        _, columns = await connection.execute_query("PRAGMA table_info('opentrades')")
        statements = _plan_additive_column_statements(
            "opentrades",
            {row["name"] for row in columns},
            tuple(
                (name, "TEXT NULL")
                for name in (
                    "accumulation_net_quantity",
                    "accumulation_remaining_cost",
                    "accumulation_contributed_quote",
                    "accumulation_disposal_proceeds",
                    "accumulation_fees_json",
                    "accumulation_basis_provenance",
                )
            ),
        )
        if statements:
            await connection.execute_script("\n".join(statements))

    async def _ensure_strategy_history_schema(self) -> None:
        """Add strategy identity columns and their lookup index."""
        await self._ensure_trade_ledger_columns()
        await self._ensure_strategy_history_index()

    async def _ensure_strategy_history_index(self) -> None:
        """Create the strategy lookup index after its columns exist."""
        if not self.db_url.startswith("sqlite://"):
            return

        connection = Tortoise.get_connection("default")
        await connection.execute_script("""
            CREATE INDEX IF NOT EXISTS idx_tradeexecutions_strategy_version
            ON tradeexecutions (strategy_slug, strategy_version);
            """)

    async def _run_backfill_init_steps(self) -> None:
        """Run ordered data migrations required before the runtime starts."""
        await run_schema_migrations(
            (
                MigrationDefinition(
                    version="2026-07-28-007-trade-ledger-backfill",
                    phase="data",
                    description="Backfill deal identity and execution-ledger rows.",
                    apply=self._backfill_trade_ledger_rows,
                ),
            )
        )

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
            await bootstrap_sqlite_migration_ledger(db_url)
            await self._assert_no_orphaned_campaign_rebuild_tables(db_url)
            # Generate the schema
            await Tortoise.generate_schemas()
            # The preflight reads the ledger before any migration callback runs,
            # so it reflects the install's last-known baseline. It is report-only:
            # a preflight failure must never block startup.
            try:
                baseline = await preflight_msv()
                if not baseline.supported:
                    logging.warning(
                        "Database baseline is %s; minimum supported version is %s. %s",
                        baseline.summary,
                        MINIMUM_SUPPORTED_VERSION,
                        baseline.upgrade_guidance,
                    )
            except Exception:  # noqa: BLE001 - the preflight must never block startup.
                logging.exception("MSV preflight failed; continuing startup.")
            await self._run_schema_init_steps()
            await self._repair_index_only_corruption_if_needed()
            await self._run_backfill_init_steps()
            logging.info("Database initialized successfully")
        except Exception as exc:  # noqa: BLE001 - Catch all exceptions during init
            if _is_sqlite_malformed_error(exc):
                db_path = _resolve_sqlite_db_path(self.db_url or db_url)
                integrity_messages = await self._run_sqlite_integrity_check()
                message = _build_sqlite_corruption_message(
                    db_path,
                    integrity_messages,
                )
                logging.error(message, exc_info=True)
                raise RuntimeError(message) from exc
            logging.error("Failed to initialize database: %s", exc, exc_info=True)
            raise

    async def backfill_trade_replay_candles_if_needed(self) -> None:
        """Backfill replay archives in the background after startup."""
        if not self.db_url.startswith("sqlite://"):
            return

        try:
            await self._backfill_trade_replay_candles()
        except asyncio.CancelledError:
            logging.info("Background replay archive backfill cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - keep startup background-safe.
            logging.error(
                "Background replay archive backfill failed: %s",
                exc,
                exc_info=True,
            )

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
