"""Backup and restore helpers for config and trade data."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import helper
import model
from service.accumulation.backup import (
    ACCUMULATION_TABLE_MODELS,
    export_strategy_dependencies,
    restore_strategy_dependencies,
    safe_accumulation_row,
    validate_accumulation_backup,
)
from service.backup_vintage import (
    SIDESTEP_WAITING_STATE_COLUMNS,
    campaign_residue_rows,
    campaign_residue_symbols,
)
from service.config import (
    Config,
    build_removed_config_key_message,
    bump_config_revision,
    is_removed_config_key,
    resolve_history_lookback_days,
)
from service.data import Data
from service.database import run_sqlite_write_with_retry
from service.msv import LEGACY_TRADE_MODE_KEYS
from service.placement_intents import (
    NONTERMINAL_PLACEMENT_STATES,
    TERMINAL_PLACEMENT_STATES,
    is_terminal_placement_state,
    quarantine_restored_intent,
)
from service.trade_lifecycle_config import build_invalid_backup_shape_error
from tortoise import fields
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger("logs/config.log", "config")

BACKUP_SCHEMA_VERSION = 3
RECOVERY_MANIFEST_SCHEMA_VERSION = 1
RECOVERY_MANIFEST_DISPOSITION = "quarantine_only"

# Pre-4.9 backups may still carry the raw trade-mode bridge keys. Restore
# drops them silently (decision D11, 2026-11-01): every legacy representation
# was equivalent to the default `trade_mode` value (`dynamic_dca`), so
# dropping them loses nothing and keeps old backups restorable without operator
# action. See docs/operations.md, "Backup And Restore".

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
    **ACCUMULATION_TABLE_MODELS,
}


def _serialize_value(value: Any) -> Any:
    """Normalize ORM values into JSON-safe primitives."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def _finding(
    code: str,
    severity: str,
    message: str,
    detail: Any = None,
    next_action: str | None = None,
) -> dict[str, Any]:
    """Build one JSON-safe classification finding."""
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "detail": detail,
        "next_action": next_action,
    }


def _forced_dry_run_pause_finding() -> dict[str, Any]:
    """The guaranteed post-restore state, stated before the operator commits."""
    return _finding(
        "forced_dry_run_pause",
        "info",
        "A restore always finishes with the instance paused in dry-run mode; "
        "review the restored state before activating and resuming trading.",
    )


class BackupService:
    """Export and restore persisted config and trade data."""

    async def export_backup(self, include_trade_data: bool) -> dict[str, Any]:
        """Build a JSON-safe backup payload."""
        async with in_transaction() as connection:
            return await self._export_snapshot(include_trade_data, connection)

    async def _export_snapshot(
        self, include_trade_data: bool, connection: BaseDBAsyncClient
    ) -> dict[str, Any]:
        """Read ownership, checkpoints and journals from one database snapshot."""
        config_rows = [
            row
            for row in await model.AppConfig.all()
            .using_db(connection)
            .order_by("id")
            .values()
            if not is_removed_config_key(str(row.get("key") or ""))
        ]
        payload: dict[str, Any] = {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "includes_trade_data": include_trade_data,
            "config": self._serialize_rows(config_rows),
        }
        if include_trade_data:
            payload["trade_data"] = await self._export_trade_data(connection)
            payload["sealed_recovery_manifest"] = await self._export_recovery_manifest(
                connection
            )
            dependencies = await export_strategy_dependencies(
                payload["trade_data"], connection, config_rows
            )
            payload["accumulation_strategies"] = {
                key: self._serialize_rows(rows) for key, rows in dependencies.items()
            }
        return payload

    async def restore_backup(
        self,
        backup_payload: dict[str, Any],
        *,
        restore_trade_data: bool,
    ) -> dict[str, Any]:
        """Restore config-only or full backup payloads."""
        if backup_payload.get("schema_version", 1) not in {1, 2, 3}:
            raise ValueError("Unsupported backup schema version.")
        config_rows = self._force_safe_restore_config(
            self._validate_config_rows(backup_payload.get("config"))
        )

        trade_data = backup_payload.get("trade_data")
        if restore_trade_data:
            if not isinstance(trade_data, dict):
                raise build_invalid_backup_shape_error(
                    message="Full restore requires a backup that includes trade data.",
                    safe_fields={"restore_trade_data": restore_trade_data},
                )
            validated_trade_data = self._validate_trade_data(trade_data)
            self._assert_no_open_trade_campaign_residue(validated_trade_data)
            if any(validated_trade_data[name] for name in ACCUMULATION_TABLE_MODELS):
                if not ACCUMULATION_TABLE_MODELS.keys() <= trade_data.keys():
                    raise ValueError("Accumulation backup is missing ownership tables.")
            quarantined_intents = self._validate_recovery_manifest(
                backup_payload.get("sealed_recovery_manifest")
            )
            dependencies = validate_accumulation_backup(
                validated_trade_data,
                quarantined_intents,
                backup_payload.get("accumulation_strategies"),
                config_rows,
            )
        else:
            # A local numeric version ID is not portable without its immutable
            # document. Config-only restore requires an explicit new selection.
            config_rows = [
                row
                for row in config_rows
                if row["key"] != "accumulation_strategy_version_id"
            ]
            validated_trade_data = None
            quarantined_intents = []
            dependencies = {"definitions": [], "versions": []}

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
                await bump_config_revision(conn)
                await model.AppConfig.all().using_db(conn).delete()
                for row in config_rows:
                    await model.AppConfig.create(using_db=conn, **row)

                if not validated_trade_data:
                    return

                await restore_strategy_dependencies(dependencies, conn)
                for model_class in reversed(ACCUMULATION_TABLE_MODELS.values()):
                    await model_class.all().using_db(conn).delete()
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
                    if table_name in ACCUMULATION_TABLE_MODELS:
                        continue
                    model_class = TRADE_TABLE_MODELS[table_name]
                    for row in rows:
                        await self._create_restored_row(
                            model_class,
                            self._deserialize_row(
                                model_class, safe_accumulation_row(table_name, row)
                            ),
                            conn,
                        )
                if (
                    await model.ClosedTrades.filter(
                        close_reason="manual_stop", valuation_quantity__isnull=True
                    )
                    .using_db(conn)
                    .exists()
                ):
                    await (
                        model.UpnlHistory.all()
                        .using_db(conn)
                        .update(performance_verified=False)
                    )
                accumulation_symbols = {
                    row["symbol"]
                    for row in validated_trade_data["accumulation_activations"]
                }
                for row in quarantined_intents:
                    restored = quarantine_restored_intent(row)
                    restored["id"] = row.get("id")
                    if row["symbol"] in accumulation_symbols:
                        # Embedded identities and cumulative evidence are audit data;
                        # quarantine blocks all lookup/accounting until explicit repair.
                        restored = {
                            **row,
                            "state": "restored_quarantined",
                            "reason_code": "portable_restore_quarantine",
                        }
                    await self._create_restored_row(
                        model.PlacementIntent,
                        self._deserialize_row(model.PlacementIntent, restored),
                        conn,
                    )
                for table_name, model_class in ACCUMULATION_TABLE_MODELS.items():
                    for row in validated_trade_data[table_name]:
                        await self._create_restored_row(
                            model_class,
                            self._deserialize_row(
                                model_class, safe_accumulation_row(table_name, row)
                            ),
                            conn,
                        )

        config = await Config.instance()
        lock = await config._acquire_write_lock()
        async with lock:
            await run_sqlite_write_with_retry(_restore, "restoring backup")
            await config.reload()

        if validated_trade_data:
            refreshed, failed = await self._refresh_required_history(config.snapshot())
            restore_summary["history_refreshed_symbols"] = refreshed
            restore_summary["history_failed_symbols"] = failed

        return restore_summary

    def classify_backup(
        self,
        backup_payload: dict[str, Any],
        *,
        restore_trade_data: bool,
    ) -> dict[str, Any]:
        """Classify a backup payload against the current restore semantics.

        Runs the restore's own validation primitives as a collect-all pass and
        reports every finding without touching any state. Findings with
        severity ``blocking`` mirror the refusal the restore would raise;
        ``warning`` findings name the silent drops the restore performs;
        ``info`` findings state the guaranteed post-restore outcome. The
        restore endpoint remains the authoritative gate: this preview never
        mutates and never bypasses it.

        Args:
            backup_payload: The parsed backup document to classify.
            restore_trade_data: Whether the classification is for a full
                restore (trade data included) or a config-only restore.

        Returns:
            A JSON-safe document with a ``classification`` summary and the
            ordered ``findings`` list (blocking first, then warning, then
            info).
        """
        findings: list[dict[str, Any]] = []
        schema_version = backup_payload.get("schema_version", 1)
        if schema_version not in {1, 2, 3}:
            findings.append(
                _finding(
                    "unsupported_schema_version",
                    "blocking",
                    "Unsupported backup schema version.",
                    detail={"schema_version": schema_version},
                )
            )
            findings.append(_forced_dry_run_pause_finding())
            return self._build_classification(
                backup_payload,
                schema_version,
                trade_mode_era=None,
                bridge_keys=frozenset(),
                includes_accumulation=False,
                findings=findings,
            )

        bridge_keys, kept_rows, config_findings = self._classify_config_rows(
            backup_payload.get("config")
        )
        findings.extend(config_findings)
        if bridge_keys:
            findings.append(
                _finding(
                    "legacy_bridge_keys_dropped",
                    "warning",
                    f"{len(bridge_keys)} legacy trade-mode key(s) will be "
                    "dropped on restore; every pre-4.9 representation was "
                    "equivalent to the default dynamic_dca mode.",
                    detail={"keys": sorted(bridge_keys)},
                )
            )

        trade_data = backup_payload.get("trade_data")
        validated_trade_data: dict[str, list[dict[str, Any]]] | None = None
        quarantined_intents: list[dict[str, Any]] = []
        if restore_trade_data:
            if not isinstance(trade_data, dict):
                findings.append(
                    _finding(
                        "invalid_trade_data",
                        "blocking",
                        "Full restore requires a backup that includes trade data.",
                        detail={"restore_trade_data": restore_trade_data},
                    )
                )
            else:
                (
                    validated_trade_data,
                    trade_findings,
                    dropped_columns,
                ) = self._classify_trade_data(trade_data)
                findings.extend(trade_findings)
                if dropped_columns:
                    findings.append(self._dropped_columns_finding(dropped_columns))
                residue_rows = campaign_residue_rows(
                    validated_trade_data.get("open_trades", [])
                )
                if residue_rows:
                    findings.append(
                        _finding(
                            "campaign_residue",
                            "blocking",
                            f"Restore aborted: the backup has "
                            f"{len(residue_rows)} open trade row(s) with "
                            "legacy campaign residue (symbols: "
                            f"{', '.join(campaign_residue_symbols(residue_rows))}). "
                            "The campaign columns were dropped in 4.9, so "
                            "restoring would silently lose the campaign "
                            "linkage. Review the open position(s) on the "
                            "exchange, clear the campaign_id value(s) in the "
                            "backup's open-trade rows, then retry; see "
                            'docs/operations.md, "Campaign residue recovery".',
                            detail={
                                "count": len(residue_rows),
                                "symbols": campaign_residue_symbols(residue_rows),
                            },
                        )
                    )
                if any(
                    validated_trade_data[name] for name in ACCUMULATION_TABLE_MODELS
                ):
                    if not ACCUMULATION_TABLE_MODELS.keys() <= trade_data.keys():
                        findings.append(
                            _finding(
                                "accumulation_incomplete",
                                "blocking",
                                "Accumulation backup is missing ownership tables.",
                            )
                        )
                quarantined_intents, manifest_findings = (
                    self._classify_recovery_manifest(
                        backup_payload.get("sealed_recovery_manifest")
                    )
                )
                findings.extend(manifest_findings)
                if quarantined_intents:
                    findings.append(
                        _finding(
                            "quarantined_intents",
                            "warning",
                            f"{len(quarantined_intents)} placement intent(s) "
                            "will be restored in quarantine and require "
                            "explicit repair before trading can use them.",
                            detail={"count": len(quarantined_intents)},
                            next_action=(
                                'See docs/operations.md, "Startup Recovery", '
                                "for the repair flow."
                            ),
                        )
                    )
                # The restore only reaches the accumulation validation with a
                # structurally valid manifest; a broken manifest is already
                # reported as blocking above.
                if not manifest_findings:
                    try:
                        validate_accumulation_backup(
                            validated_trade_data,
                            quarantined_intents,
                            backup_payload.get("accumulation_strategies"),
                            kept_rows,
                        )
                    except (ValueError, KeyError, TypeError) as exc:
                        findings.append(
                            _finding(
                                "accumulation_incomplete",
                                "blocking",
                                str(exc) or "Accumulation backup validation failed.",
                            )
                        )
        else:
            if any(
                row["key"] == "accumulation_strategy_version_id" for row in kept_rows
            ):
                findings.append(
                    _finding(
                        "accumulation_version_id_dropped",
                        "warning",
                        "The local strategy pin (accumulation_strategy_"
                        "version_id) will be removed because a numeric pin "
                        "is not portable without its immutable document; "
                        "reselect the strategy after restoring.",
                        detail={"key": "accumulation_strategy_version_id"},
                    )
                )

        trade_mode_value: str | None = None
        for row in kept_rows:
            if row["key"] == "trade_mode":
                trade_mode_value = str(row.get("value") or "").strip() or None
        includes_accumulation = bool(validated_trade_data) and (
            any(validated_trade_data.get(name) for name in ACCUMULATION_TABLE_MODELS)
            or any(
                row.get("lifecycle_mode") == "accumulation"
                for row in validated_trade_data.get("open_trades", [])
            )
            or bool(backup_payload.get("accumulation_strategies"))
        )
        if trade_mode_value == "accumulation" or includes_accumulation:
            trade_mode_era = "accumulation"
        elif trade_mode_value == "dynamic_dca":
            trade_mode_era = "dynamic_dca"
        else:
            trade_mode_era = "legacy_unspecified"

        findings.append(_forced_dry_run_pause_finding())
        return self._build_classification(
            backup_payload,
            schema_version,
            trade_mode_era=trade_mode_era,
            bridge_keys=bridge_keys,
            includes_accumulation=includes_accumulation,
            findings=findings,
        )

    @staticmethod
    def _build_classification(
        backup_payload: dict[str, Any],
        schema_version: Any,
        trade_mode_era: str | None,
        bridge_keys: frozenset[str],
        includes_accumulation: bool,
        findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Assemble the classification document with findings ordered by severity."""
        severity_rank = {"blocking": 0, "warning": 1, "info": 2}
        findings.sort(key=lambda finding: severity_rank.get(finding["severity"], 3))
        return {
            "classification": {
                "schema_version": (
                    schema_version if isinstance(schema_version, int) else None
                ),
                "trade_mode_era": trade_mode_era,
                "pre_4_9_bridge_keys": sorted(bridge_keys),
                "includes_accumulation": includes_accumulation,
            },
            "findings": findings,
        }

    @staticmethod
    def _classify_config_rows(
        raw_rows: Any,
    ) -> tuple[frozenset[str], list[dict[str, Any]], list[dict[str, Any]]]:
        """Mirror the restore's config validation as a collect-all pass."""
        findings: list[dict[str, Any]] = []
        if not isinstance(raw_rows, list):
            findings.append(
                _finding(
                    "invalid_config",
                    "blocking",
                    "Backup does not contain valid config rows.",
                    detail={"config_type": type(raw_rows).__name__},
                )
            )
            return frozenset(), [], findings

        bridge_keys: set[str] = set()
        kept_rows: list[dict[str, Any]] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                findings.append(
                    _finding(
                        "invalid_config",
                        "blocking",
                        "Backup config rows must be objects.",
                        detail={"row_type": type(raw_row).__name__},
                    )
                )
                continue
            key = str(raw_row.get("key") or "").strip()
            value_type = str(raw_row.get("value_type") or "").strip()
            if not key or not value_type:
                findings.append(
                    _finding(
                        "invalid_config",
                        "blocking",
                        "Backup config rows must include key and value_type.",
                        detail={"key": key or None, "value_type": value_type or None},
                    )
                )
                continue
            if key in LEGACY_TRADE_MODE_KEYS:
                bridge_keys.add(key)
                continue
            if is_removed_config_key(key):
                findings.append(
                    _finding(
                        "removed_config_key",
                        "blocking",
                        build_removed_config_key_message(key),
                        detail={"key": key},
                    )
                )
                continue
            kept_rows.append(
                {
                    "key": key,
                    "value": raw_row.get("value"),
                    "value_type": value_type,
                }
            )
        return frozenset(bridge_keys), kept_rows, findings

    @staticmethod
    def _classify_trade_data(
        raw_trade_data: dict[str, Any],
    ) -> tuple[
        dict[str, list[dict[str, Any]]],
        list[dict[str, Any]],
        dict[str, dict[str, int]],
    ]:
        """Mirror the restore's trade-data validation as a collect-all pass.

        Returns the normalized rows, the blocking findings, and the per-table
        counts of row values whose columns no longer exist in the current
        model (the values restore will silently drop).
        """
        findings: list[dict[str, Any]] = []
        validated: dict[str, list[dict[str, Any]]] = {}
        dropped_columns: dict[str, dict[str, int]] = {}
        for table_name, model_class in TRADE_TABLE_MODELS.items():
            raw_rows = raw_trade_data.get(table_name, [])
            if not isinstance(raw_rows, list):
                findings.append(
                    _finding(
                        "invalid_trade_data",
                        "blocking",
                        f"Backup trade data for '{table_name}' must be a list.",
                        detail={
                            "table_name": table_name,
                            "value_type": type(raw_rows).__name__,
                        },
                    )
                )
                continue
            normalized_rows: list[dict[str, Any]] = []
            table_dropped: dict[str, int] = {}
            for raw_row in raw_rows:
                if not isinstance(raw_row, dict):
                    findings.append(
                        _finding(
                            "invalid_trade_data",
                            "blocking",
                            f"Backup trade data for '{table_name}' must "
                            "contain objects.",
                            detail={
                                "table_name": table_name,
                                "row_type": type(raw_row).__name__,
                            },
                        )
                    )
                    continue
                if table_name == "placement_intents" and not (
                    is_terminal_placement_state(raw_row.get("state"))
                ):
                    findings.append(
                        _finding(
                            "invalid_placement_intents",
                            "blocking",
                            "Portable placement audit rows must be terminal; "
                            "nonterminal rows belong in the sealed recovery "
                            "manifest.",
                            detail={
                                "table_name": table_name,
                                "state": raw_row.get("state"),
                            },
                        )
                    )
                fields_map = model_class._meta.fields_map
                for key in raw_row:
                    if key not in fields_map:
                        table_dropped[key] = table_dropped.get(key, 0) + 1
                normalized_rows.append(dict(raw_row))
            validated[table_name] = normalized_rows
            if table_dropped:
                dropped_columns[table_name] = table_dropped
        return validated, findings, dropped_columns

    @staticmethod
    def _dropped_columns_finding(
        dropped_columns: dict[str, dict[str, int]],
    ) -> dict[str, Any]:
        """Name the row values restore will silently drop, with era context."""
        total = sum(sum(counts.values()) for counts in dropped_columns.values())
        columns_text = ", ".join(
            f"{table}.{column} ({count})"
            for table, counts in sorted(dropped_columns.items())
            for column, count in sorted(counts.items())
        )
        message = (
            f"{total} trade data value(s) will be dropped because their "
            f"columns no longer exist in the current schema: {columns_text}."
        )
        legacy_names = {
            column
            for counts in dropped_columns.values()
            for column in counts
            if column in SIDESTEP_WAITING_STATE_COLUMNS
        }
        if legacy_names:
            message += (
                " The waiting-state values are legacy sidestep-era state that "
                "no live code reads."
            )
        return _finding(
            "dropped_trade_columns",
            "warning",
            message,
            detail=dropped_columns,
        )

    @classmethod
    def _classify_recovery_manifest(
        cls, raw_manifest: Any
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Mirror the restore's manifest validation as a collect-all pass."""
        if raw_manifest is None:
            return [], []
        findings: list[dict[str, Any]] = []
        if not isinstance(raw_manifest, dict):
            findings.append(
                _finding(
                    "manifest_invalid",
                    "blocking",
                    "The recovery manifest must be an object.",
                    detail={"manifest_type": type(raw_manifest).__name__},
                )
            )
            return [], findings
        raw_intents = raw_manifest.get("intents")
        if not isinstance(raw_intents, list):
            findings.append(
                _finding(
                    "manifest_invalid",
                    "blocking",
                    "The recovery manifest intents must be a list.",
                    detail={"intents_type": type(raw_intents).__name__},
                )
            )
            return [], findings
        body = {
            "schema_version": raw_manifest.get("schema_version"),
            "disposition": raw_manifest.get("disposition"),
            "intents": raw_intents,
        }
        if body["schema_version"] != RECOVERY_MANIFEST_SCHEMA_VERSION:
            findings.append(
                _finding(
                    "manifest_invalid",
                    "blocking",
                    "Unsupported recovery manifest schema version.",
                    detail={"schema_version": body["schema_version"]},
                )
            )
        if body["disposition"] != RECOVERY_MANIFEST_DISPOSITION:
            findings.append(
                _finding(
                    "manifest_invalid",
                    "blocking",
                    "Recovery manifests may only restore into quarantine.",
                    detail={"disposition": body["disposition"]},
                )
            )
        if raw_manifest.get("sha256") != cls._recovery_manifest_digest(body):
            findings.append(
                _finding(
                    "manifest_invalid",
                    "blocking",
                    "The recovery manifest checksum validation failed.",
                    detail={"manifest_intents": len(raw_intents)},
                )
            )
        validated: list[dict[str, Any]] = []
        for raw_intent in raw_intents:
            if not isinstance(raw_intent, dict):
                findings.append(
                    _finding(
                        "manifest_invalid",
                        "blocking",
                        "Recovery manifest intents must be objects.",
                        detail={"intent_type": type(raw_intent).__name__},
                    )
                )
                continue
            state = str(raw_intent.get("state") or "")
            if state not in NONTERMINAL_PLACEMENT_STATES:
                findings.append(
                    _finding(
                        "manifest_invalid",
                        "blocking",
                        "Recovery manifest intents must be nonterminal.",
                        detail={"state": state},
                    )
                )
                continue
            validated.append(dict(raw_intent))
        if findings:
            return [], findings
        return validated, findings

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

    @staticmethod
    async def _create_restored_row(
        model_class: Any, payload: dict[str, Any], connection: BaseDBAsyncClient
    ) -> None:
        """Preserve source chronology after ORM auto-now insert hooks run."""
        restored = await model_class.create(using_db=connection, **payload)
        timestamps = {
            name: payload[name]
            for name, field in model_class._meta.fields_map.items()
            if isinstance(field, fields.DatetimeField)
            and field.auto_now
            and name in payload
            and payload[name] is not None
        }
        if timestamps:
            await (
                model_class.filter(pk=restored.pk)
                .using_db(connection)
                .update(**timestamps)
            )

    async def _export_trade_data(
        self, connection: BaseDBAsyncClient
    ) -> dict[str, list[dict[str, Any]]]:
        """Export trade-related tables, excluding ticker OHLCV data."""
        payload: dict[str, list[dict[str, Any]]] = {}
        for table_name, model_class in TRADE_TABLE_MODELS.items():
            query = model_class.all().using_db(connection)
            if model_class is model.PlacementIntent:
                query = query.filter(state__in=TERMINAL_PLACEMENT_STATES)
            rows = await query.order_by("id").values()
            payload[table_name] = self._serialize_rows(rows)
        return payload

    async def _export_recovery_manifest(
        self, connection: BaseDBAsyncClient
    ) -> dict[str, Any]:
        """Checksum nonterminal intents for audit-only quarantine on restore."""
        rows = (
            await model.PlacementIntent.filter(state__in=NONTERMINAL_PLACEMENT_STATES)
            .using_db(connection)
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
        """Return a checksum that detects accidental manifest corruption."""
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
            if key in LEGACY_TRADE_MODE_KEYS:
                continue
            if is_removed_config_key(key):
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

    @staticmethod
    def _assert_no_open_trade_campaign_residue(
        validated_trade_data: dict[str, list[dict[str, Any]]],
    ) -> None:
        """Refuse a full restore whose open trades still reference a campaign.

        Mirrors the startup residue gate in ``Database.init``: the campaign
        columns were dropped in the 4.9 contract migration, so deserializing
        a pre-4.9 backup row that still carries ``campaign_id`` would silently
        lose the campaign linkage without the operator review the startup gate
        requires. The documented recovery procedure must run first.
        """
        residue_rows = campaign_residue_rows(
            validated_trade_data.get("open_trades", [])
        )
        if not residue_rows:
            return
        symbols = ", ".join(campaign_residue_symbols(residue_rows))
        raise ValueError(
            "Restore aborted: the backup has "
            f"{len(residue_rows)} open trade row(s) with legacy campaign "
            f"residue (symbols: {symbols}). The campaign columns were dropped "
            "in 4.9, so restoring would silently lose the campaign linkage. "
            "Review the open position(s) on the exchange, clear the "
            "campaign_id value(s) in the backup's open-trade rows, then "
            'retry; see docs/operations.md, "Campaign residue recovery".'
        )

    @classmethod
    def _validate_recovery_manifest(
        cls,
        raw_manifest: Any,
    ) -> list[dict[str, Any]]:
        """Validate a checksummed manifest and return nonterminal source intents.

        The legacy ``sealed_recovery_manifest`` field name remains part of the
        backup schema. Its plain SHA-256 digest detects corruption but does not
        authenticate a backup supplied by an untrusted party.
        """
        if raw_manifest is None:
            return []
        if not isinstance(raw_manifest, dict):
            raise build_invalid_backup_shape_error(
                message="The recovery manifest must be an object.",
                safe_fields={"manifest_type": type(raw_manifest).__name__},
            )

        raw_intents = raw_manifest.get("intents")
        if not isinstance(raw_intents, list):
            raise build_invalid_backup_shape_error(
                message="The recovery manifest intents must be a list.",
                safe_fields={"intents_type": type(raw_intents).__name__},
            )
        body = {
            "schema_version": raw_manifest.get("schema_version"),
            "disposition": raw_manifest.get("disposition"),
            "intents": raw_intents,
        }
        if body["schema_version"] != RECOVERY_MANIFEST_SCHEMA_VERSION:
            raise build_invalid_backup_shape_error(
                message="Unsupported recovery manifest schema version.",
                safe_fields={"schema_version": body["schema_version"]},
            )
        if body["disposition"] != RECOVERY_MANIFEST_DISPOSITION:
            raise build_invalid_backup_shape_error(
                message="Recovery manifests may only restore into quarantine.",
                safe_fields={"disposition": body["disposition"]},
            )
        if raw_manifest.get("sha256") != cls._recovery_manifest_digest(body):
            raise build_invalid_backup_shape_error(
                message="The recovery manifest checksum validation failed.",
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
    def _deserialize_row(model_class: type, row: dict[str, Any]) -> dict[str, Any]:
        """Convert serialized backup values into ORM-create payloads."""
        payload: dict[str, Any] = {}
        for key, value in row.items():
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
                except Exception as exc:  # noqa: BLE001 - report restore warnings, continue.
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
