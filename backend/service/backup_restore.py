"""Backup and restore helpers for config and trade data."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import helper
import model
from service.config import Config, resolve_history_lookback_days
from service.data import Data
from service.database import run_sqlite_write_with_retry
from tortoise import fields
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger("logs/config.log", "backup_restore")

BACKUP_SCHEMA_VERSION = 1

TRADE_TABLE_MODELS: dict[str, type] = {
    "trades": model.Trades,
    "open_trades": model.OpenTrades,
    "closed_trades": model.ClosedTrades,
    "unsellable_trades": model.UnsellableTrades,
    "autopilot_history": model.Autopilot,
    "upnl_history": model.UpnlHistory,
}


def _serialize_value(value: Any) -> Any:
    """Normalize ORM values into JSON-safe primitives."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


class BackupService:
    """Export and restore persisted config and trade data."""

    async def export_backup(self, include_trade_data: bool) -> dict[str, Any]:
        """Build a JSON-safe backup payload."""
        config_rows = await model.AppConfig.all().order_by("id").values()
        payload: dict[str, Any] = {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "includes_trade_data": include_trade_data,
            "config": self._serialize_rows(config_rows),
        }
        if include_trade_data:
            payload["trade_data"] = await self._export_trade_data()
        return payload

    async def restore_backup(
        self,
        backup_payload: dict[str, Any],
        *,
        restore_trade_data: bool,
    ) -> dict[str, Any]:
        """Restore config-only or full backup payloads."""
        config_rows = self._validate_config_rows(backup_payload.get("config"))
        trade_data = backup_payload.get("trade_data")
        if restore_trade_data:
            if not isinstance(trade_data, dict):
                raise ValueError(
                    "Full restore requires a backup that includes trade data."
                )
            validated_trade_data = self._validate_trade_data(trade_data)
        else:
            validated_trade_data = None

        restore_summary = {
            "config_keys": len(config_rows),
            "trade_tables": {
                table_name: len(rows)
                for table_name, rows in (validated_trade_data or {}).items()
            },
            "history_refreshed_symbols": [],
            "history_failed_symbols": [],
        }

        async def _restore() -> None:
            async with in_transaction() as conn:
                await model.AppConfig.all().using_db(conn).delete()
                for row in config_rows:
                    await model.AppConfig.create(using_db=conn, **row)

                if not validated_trade_data:
                    return

                await model.Tickers.all().using_db(conn).delete()
                await model.UpnlHistory.all().using_db(conn).delete()
                await model.Autopilot.all().using_db(conn).delete()
                await model.UnsellableTrades.all().using_db(conn).delete()
                await model.OpenTrades.all().using_db(conn).delete()
                await model.ClosedTrades.all().using_db(conn).delete()
                await model.Trades.all().using_db(conn).delete()

                for table_name, rows in validated_trade_data.items():
                    model_class = TRADE_TABLE_MODELS[table_name]
                    for row in rows:
                        await model_class.create(
                            using_db=conn,
                            **self._deserialize_row(model_class, row),
                        )

        await run_sqlite_write_with_retry(_restore, "restoring backup")

        config = await Config.instance()
        await config.reload()

        if validated_trade_data:
            refreshed, failed = await self._refresh_required_history(config.snapshot())
            restore_summary["history_refreshed_symbols"] = refreshed
            restore_summary["history_failed_symbols"] = failed

        return restore_summary

    async def _export_trade_data(self) -> dict[str, list[dict[str, Any]]]:
        """Export trade-related tables, excluding ticker OHLCV data."""
        payload: dict[str, list[dict[str, Any]]] = {}
        for table_name, model_class in TRADE_TABLE_MODELS.items():
            rows = await model_class.all().order_by("id").values()
            payload[table_name] = self._serialize_rows(rows)
        return payload

    @staticmethod
    def _serialize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert a list of ORM row dicts into JSON-safe dicts."""
        serialized_rows: list[dict[str, Any]] = []
        for row in rows:
            serialized_rows.append(
                {key: _serialize_value(value) for key, value in row.items()}
            )
        return serialized_rows

    @staticmethod
    def _validate_config_rows(raw_rows: Any) -> list[dict[str, Any]]:
        """Validate and normalize backup config rows."""
        if not isinstance(raw_rows, list):
            raise ValueError("Backup does not contain valid config rows.")

        normalized_rows: list[dict[str, Any]] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                raise ValueError("Backup config rows must be objects.")
            key = str(raw_row.get("key") or "").strip()
            value_type = str(raw_row.get("value_type") or "").strip()
            if not key or not value_type:
                raise ValueError("Backup config rows must include key and value_type.")
            normalized_rows.append(
                {
                    "key": key,
                    "value": raw_row.get("value"),
                    "value_type": value_type,
                }
            )
        return normalized_rows

    @staticmethod
    def _validate_trade_data(
        raw_trade_data: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        """Validate and normalize trade-data sections from backup."""
        validated: dict[str, list[dict[str, Any]]] = {}
        for table_name in TRADE_TABLE_MODELS:
            raw_rows = raw_trade_data.get(table_name, [])
            if not isinstance(raw_rows, list):
                raise ValueError(
                    f"Backup trade data for '{table_name}' must be a list."
                )
            normalized_rows: list[dict[str, Any]] = []
            for raw_row in raw_rows:
                if not isinstance(raw_row, dict):
                    raise ValueError(
                        f"Backup trade data for '{table_name}' must contain objects."
                    )
                normalized_rows.append(dict(raw_row))
            validated[table_name] = normalized_rows
        return validated

    @staticmethod
    def _deserialize_row(model_class: type, row: dict[str, Any]) -> dict[str, Any]:
        """Convert serialized backup values into ORM-create payloads."""
        payload: dict[str, Any] = {}
        for key, value in row.items():
            if key == "id":
                continue
            field = model_class._meta.fields_map.get(key)
            if field is None:
                continue
            if value is None:
                payload[key] = None
                continue
            if isinstance(field, fields.DatetimeField) and isinstance(value, str):
                payload[key] = datetime.fromisoformat(value)
                continue
            if isinstance(field, fields.DecimalField):
                payload[key] = Decimal(str(value))
                continue
            payload[key] = value
        return payload

    async def _refresh_required_history(
        self, config: dict[str, Any]
    ) -> tuple[list[str], list[str]]:
        """Fetch ticker history again for restored active trades."""
        symbols = await model.Trades.all().distinct().values_list("symbol", flat=True)
        unique_symbols = sorted(
            {str(symbol) for symbol in symbols if str(symbol).strip()}
        )
        if not unique_symbols:
            return [], []

        history_days = resolve_history_lookback_days(config)
        data = Data(persist_exchange=True)
        refreshed_symbols: list[str] = []
        failed_symbols: list[str] = []
        try:
            for symbol in unique_symbols:
                try:
                    history_ok = await data.add_history_data_for_symbol(
                        symbol,
                        history_days,
                        config,
                    )
                except (
                    Exception
                ) as exc:  # noqa: BLE001 - report restore warnings, continue.
                    logging.error(
                        "Failed refreshing restored ticker history for %s: %s",
                        symbol,
                        exc,
                    )
                    history_ok = False

                if history_ok:
                    refreshed_symbols.append(symbol)
                else:
                    failed_symbols.append(symbol)
        finally:
            await data.close()

        return refreshed_symbols, failed_symbols
