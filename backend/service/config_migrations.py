"""Versioned, transactional migrations for persisted configuration."""

from __future__ import annotations

import json
from typing import Any

from model import AppConfig, ConfigMigration
from service.signal_settings import SignalSettingsError, serialize_signal_settings
from tortoise.transactions import in_transaction

TRADE_MODE_MIGRATION_VERSION = "2026-07-trade-mode-v1"
SIGNAL_SETTINGS_MIGRATION_VERSION = "2026-07-signal-settings-v1"
LEGACY_TRADE_MODE_KEYS = frozenset(
    {
        "trade_lifecycle_mode",
        "dynamic_dca",
        "sidestep_campaign_enabled",
    }
)


def _deserialize_bool(value: Any) -> bool:
    """Normalize a persisted legacy boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    return bool(value)


def resolve_legacy_trade_mode(rows: list[dict[str, Any]]) -> str:
    """Resolve the canonical trade mode represented by legacy rows."""
    values = {str(row["key"]): row.get("value") for row in rows}
    lifecycle_mode = str(values.get("trade_lifecycle_mode") or "").strip()
    sidestep_enabled = _deserialize_bool(values.get("sidestep_campaign_enabled", False))
    if lifecycle_mode == "sidestep_reentry" or sidestep_enabled:
        return "sidestep"
    return "dynamic_dca"


def canonicalize_trade_mode_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert legacy backup rows to the canonical trade-mode representation."""
    canonical_rows = [
        dict(row) for row in rows if str(row.get("key")) not in LEGACY_TRADE_MODE_KEYS
    ]
    if any(str(row.get("key")) == "trade_mode" for row in canonical_rows):
        return canonical_rows

    legacy_rows = [
        dict(row) for row in rows if str(row.get("key")) in LEGACY_TRADE_MODE_KEYS
    ]
    if legacy_rows:
        canonical_rows.append(
            {
                "key": "trade_mode",
                "value": resolve_legacy_trade_mode(legacy_rows),
                "value_type": "str",
            }
        )
    return canonical_rows


async def run_config_migrations() -> None:
    """Apply all configuration migrations once in atomic transactions."""
    async with in_transaction() as connection:
        already_applied = (
            await ConfigMigration.filter(version=TRADE_MODE_MIGRATION_VERSION)
            .using_db(connection)
            .exists()
        )
        if not already_applied:
            rows = (
                await AppConfig.filter(key__in=[*LEGACY_TRADE_MODE_KEYS, "trade_mode"])
                .using_db(connection)
                .values("key", "value", "value_type")
            )
            backup_rows = sorted(rows, key=lambda row: str(row["key"]))
            has_canonical_mode = any(row["key"] == "trade_mode" for row in rows)
            legacy_rows = [row for row in rows if row["key"] in LEGACY_TRADE_MODE_KEYS]
            if legacy_rows and not has_canonical_mode:
                await AppConfig.create(
                    using_db=connection,
                    key="trade_mode",
                    value=resolve_legacy_trade_mode(legacy_rows),
                    value_type="str",
                )

            await ConfigMigration.create(
                using_db=connection,
                version=TRADE_MODE_MIGRATION_VERSION,
                backup_json=json.dumps(backup_rows, sort_keys=True),
            )

    async with in_transaction() as connection:
        already_applied = (
            await ConfigMigration.filter(version=SIGNAL_SETTINGS_MIGRATION_VERSION)
            .using_db(connection)
            .exists()
        )
        if already_applied:
            return

        row = await AppConfig.filter(key="signal_settings").using_db(connection).first()
        backup_rows = []
        if row is not None:
            backup_rows.append(
                {
                    "key": row.key,
                    "value": row.value,
                    "value_type": row.value_type,
                }
            )
            try:
                canonical_value = serialize_signal_settings(row.value)
            except SignalSettingsError:
                canonical_value = None
            if canonical_value is not None:
                await AppConfig.filter(key="signal_settings").using_db(
                    connection
                ).update(
                    value=canonical_value,
                    value_type="str",
                )

        await ConfigMigration.create(
            using_db=connection,
            version=SIGNAL_SETTINGS_MIGRATION_VERSION,
            backup_json=json.dumps(backup_rows, sort_keys=True),
        )
