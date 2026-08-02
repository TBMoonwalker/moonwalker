"""Backup and restore helpers for config and trade data."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import helper
import model
from service.config import (
    Config,
    build_removed_config_key_message,
    deserialize_config_value,
    is_removed_config_key,
    resolve_history_lookback_days,
)
from service.config_migrations import (
    LEGACY_TRADE_MODE_KEYS,
    canonicalize_trade_mode_rows,
)
from service.data import Data
from service.database import run_sqlite_write_with_retry
from service.placement_intents import (
    NONTERMINAL_PLACEMENT_STATES,
    TERMINAL_PLACEMENT_STATES,
    is_terminal_placement_state,
    quarantine_restored_intent,
)
from service.trade_lifecycle_config import (
    build_invalid_backup_shape_error,
    resolve_trade_mode_config,
)
from tortoise import fields
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger("logs/config.log", "backup_restore")

BACKUP_SCHEMA_VERSION = 2
RECOVERY_MANIFEST_SCHEMA_VERSION = 1
RECOVERY_MANIFEST_DISPOSITION = "quarantine_only"

TRADE_TABLE_MODELS: dict[str, type] = {
    "trades": model.Trades,
    "trade_executions": model.TradeExecutions,
    "trade_replay_candles": model.TradeReplayCandles,
    "open_trades": model.OpenTrades,
    "closed_trades": model.ClosedTrades,
    "unsellable_trades": model.UnsellableTrades,
    "autopilot_history": model.Autopilot,
    "upnl_history": model.UpnlHistory,
    "placement_intents": model.PlacementIntent,
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
        config_rows = [
            row
            for row in await model.AppConfig.all().order_by("id").values()
            if not is_removed_config_key(str(row.get("key") or ""))
        ]
        payload: dict[str, Any] = {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "includes_trade_data": include_trade_data,
            "config": self._serialize_rows(config_rows),
        }
        if include_trade_data:
            payload["trade_data"] = await self._export_trade_data()
            payload["sealed_recovery_manifest"] = await self._export_recovery_manifest()
        return payload

    async def restore_backup(
        self,
        backup_payload: dict[str, Any],
        *,
        restore_trade_data: bool,
    ) -> dict[str, Any]:
        """Restore config-only or full backup payloads."""
        config_rows = self._force_safe_restore_config(
            canonicalize_trade_mode_rows(
                self._validate_config_rows(backup_payload.get("config"))
            )
        )
        candidate_config = self._build_config_snapshot(config_rows)
        resolve_trade_mode_config(
            candidate_config,
            source="restore",
            require_explicit_sidestep_reentry=True,
        )
        trade_data = backup_payload.get("trade_data")
        if restore_trade_data:
            if not isinstance(trade_data, dict):
                raise build_invalid_backup_shape_error(
                    message="Full restore requires a backup that includes trade data.",
                    safe_fields={"restore_trade_data": restore_trade_data},
                )
            validated_trade_data = self._validate_trade_data(trade_data)
            quarantined_intents = self._validate_recovery_manifest(
                backup_payload.get("sealed_recovery_manifest")
            )
        else:
            validated_trade_data = None
            quarantined_intents = []

        restore_summary = {
            "config_keys": len(config_rows),
            "trade_tables": {
                table_name: len(rows)
                for table_name, rows in (validated_trade_data or {}).items()
            },
            "history_refreshed_symbols": [],
            "history_failed_symbols": [],
            "quarantined_placement_intents": len(quarantined_intents),
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
                await model.TradeReplayCandles.all().using_db(conn).delete()
                await model.TradeExecutions.all().using_db(conn).delete()
                await model.Trades.all().using_db(conn).delete()
                await model.PlacementIntent.all().using_db(conn).delete()

                for table_name, rows in validated_trade_data.items():
                    model_class = TRADE_TABLE_MODELS[table_name]
                    for row in rows:
                        await model_class.create(
                            using_db=conn,
                            **self._deserialize_row(model_class, row),
                        )
                for row in quarantined_intents:
                    await model.PlacementIntent.create(
                        using_db=conn,
                        **self._deserialize_row(
                            model.PlacementIntent,
                            quarantine_restored_intent(row),
                        ),
                    )

        await run_sqlite_write_with_retry(_restore, "restoring backup")

        config = await Config.instance()
        await config.reload()

        if validated_trade_data:
            refreshed, failed = await self._refresh_required_history(config.snapshot())
            restore_summary["history_refreshed_symbols"] = refreshed
            restore_summary["history_failed_symbols"] = failed

        return restore_summary

    @staticmethod
    def _force_safe_restore_config(
        config_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return restore rows forced into paused dry-run operation."""
        safe_rows = [dict(row) for row in config_rows]
        rows_by_key = {str(row["key"]): row for row in safe_rows}
        for key in ("dry_run", "trading_paused"):
            row = rows_by_key.get(key)
            if row is None:
                safe_rows.append(
                    {
                        "key": key,
                        "value": "True",
                        "value_type": "bool",
                    }
                )
                continue
            row["value"] = "True"
            row["value_type"] = "bool"
        return safe_rows

    async def _export_trade_data(self) -> dict[str, list[dict[str, Any]]]:
        """Export trade-related tables, excluding ticker OHLCV data."""
        payload: dict[str, list[dict[str, Any]]] = {}
        for table_name, model_class in TRADE_TABLE_MODELS.items():
            query = model_class.all()
            if model_class is model.PlacementIntent:
                query = query.filter(state__in=TERMINAL_PLACEMENT_STATES)
            rows = await query.order_by("id").values()
            payload[table_name] = self._serialize_rows(rows)
        return payload

    async def _export_recovery_manifest(self) -> dict[str, Any]:
        """Seal nonterminal intents for audit-only quarantine on restore."""
        rows = (
            await model.PlacementIntent.filter(state__in=NONTERMINAL_PLACEMENT_STATES)
            .order_by("id")
            .values()
        )
        body = {
            "schema_version": RECOVERY_MANIFEST_SCHEMA_VERSION,
            "disposition": RECOVERY_MANIFEST_DISPOSITION,
            "intents": self._serialize_rows(rows),
        }
        return {
            **body,
            "sha256": self._recovery_manifest_digest(body),
        }

    @staticmethod
    def _recovery_manifest_digest(body: dict[str, Any]) -> str:
        """Return the deterministic integrity seal for a recovery manifest."""
        canonical = json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

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
            raise build_invalid_backup_shape_error(
                message="Backup does not contain valid config rows.",
                safe_fields={"config_type": type(raw_rows).__name__},
            )

        normalized_rows: list[dict[str, Any]] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                raise build_invalid_backup_shape_error(
                    message="Backup config rows must be objects.",
                    safe_fields={"row_type": type(raw_row).__name__},
                )
            key = str(raw_row.get("key") or "").strip()
            value_type = str(raw_row.get("value_type") or "").strip()
            if not key or not value_type:
                raise build_invalid_backup_shape_error(
                    message="Backup config rows must include key and value_type.",
                    safe_fields={"key": key or None, "value_type": value_type or None},
                )
            if is_removed_config_key(key) and key not in LEGACY_TRADE_MODE_KEYS:
                raise ValueError(build_removed_config_key_message(key))
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
                raise build_invalid_backup_shape_error(
                    message=f"Backup trade data for '{table_name}' must be a list.",
                    safe_fields={
                        "table_name": table_name,
                        "value_type": type(raw_rows).__name__,
                    },
                )
            normalized_rows: list[dict[str, Any]] = []
            for raw_row in raw_rows:
                if not isinstance(raw_row, dict):
                    raise build_invalid_backup_shape_error(
                        message=(
                            f"Backup trade data for '{table_name}' must contain "
                            "objects."
                        ),
                        safe_fields={
                            "table_name": table_name,
                            "row_type": type(raw_row).__name__,
                        },
                    )
                normalized_row = dict(raw_row)
                if table_name == "placement_intents" and not (
                    is_terminal_placement_state(normalized_row.get("state"))
                ):
                    raise build_invalid_backup_shape_error(
                        message=(
                            "Portable placement audit rows must be terminal; "
                            "nonterminal rows belong in the sealed recovery manifest."
                        ),
                        safe_fields={
                            "table_name": table_name,
                            "state": normalized_row.get("state"),
                        },
                    )
                normalized_rows.append(normalized_row)
            validated[table_name] = normalized_rows
        return validated

    @classmethod
    def _validate_recovery_manifest(
        cls,
        raw_manifest: Any,
    ) -> list[dict[str, Any]]:
        """Validate a sealed manifest and return nonterminal source intents."""
        if raw_manifest is None:
            return []
        if not isinstance(raw_manifest, dict):
            raise build_invalid_backup_shape_error(
                message="The sealed recovery manifest must be an object.",
                safe_fields={"manifest_type": type(raw_manifest).__name__},
            )

        raw_intents = raw_manifest.get("intents")
        if not isinstance(raw_intents, list):
            raise build_invalid_backup_shape_error(
                message="The sealed recovery manifest intents must be a list.",
                safe_fields={"intents_type": type(raw_intents).__name__},
            )
        body = {
            "schema_version": raw_manifest.get("schema_version"),
            "disposition": raw_manifest.get("disposition"),
            "intents": raw_intents,
        }
        if body["schema_version"] != RECOVERY_MANIFEST_SCHEMA_VERSION:
            raise build_invalid_backup_shape_error(
                message="Unsupported sealed recovery manifest schema version.",
                safe_fields={"schema_version": body["schema_version"]},
            )
        if body["disposition"] != RECOVERY_MANIFEST_DISPOSITION:
            raise build_invalid_backup_shape_error(
                message="Recovery manifests may only restore into quarantine.",
                safe_fields={"disposition": body["disposition"]},
            )
        if raw_manifest.get("sha256") != cls._recovery_manifest_digest(body):
            raise build_invalid_backup_shape_error(
                message="The sealed recovery manifest integrity check failed.",
                safe_fields={"manifest_intents": len(raw_intents)},
            )

        validated: list[dict[str, Any]] = []
        for raw_intent in raw_intents:
            if not isinstance(raw_intent, dict):
                raise build_invalid_backup_shape_error(
                    message="Recovery manifest intents must be objects.",
                    safe_fields={
                        "intent_type": type(raw_intent).__name__,
                    },
                )
            state = str(raw_intent.get("state") or "")
            if state not in NONTERMINAL_PLACEMENT_STATES:
                raise build_invalid_backup_shape_error(
                    message="Recovery manifest intents must be nonterminal.",
                    safe_fields={"state": state},
                )
            validated.append(dict(raw_intent))
        return validated

    @staticmethod
    def _build_config_snapshot(config_rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a typed config snapshot from validated backup rows."""
        snapshot: dict[str, Any] = {}
        for row in config_rows:
            snapshot[row["key"]] = deserialize_config_value(
                row.get("value"),
                row["value_type"],
            )
        return snapshot

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
