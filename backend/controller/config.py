"""Configuration API endpoints."""

import json
from typing import Any

import helper
from controller.responses import json_response
from litestar.connection import Request
from litestar.exceptions import SerializationException
from litestar.handlers import get, post, put
from model import AppConfig, OpenTrades
from service.backup_restore import BackupService
from service.config import Config

logging = helper.LoggerFactory.get_logger("logs/config.log", "config_data")

CSV_SIGNAL_NAME = "csv_signal"
LIVE_ACTIVATION_KEY = "dry_run"
LIVE_ACTIVATION_DENIED_MESSAGE = (
    "Live activation must go through /config/live/activate. "
    "Generic config saves cannot switch dry run off."
)
backup_service = BackupService()


def _extract_config_update_value(raw_value: Any) -> Any:
    """Extract normalized `value` from config update payloads."""
    if isinstance(raw_value, dict) and "value" in raw_value:
        return raw_value["value"]
    return raw_value


def _is_config_update_payload(raw_value: Any) -> bool:
    """Return whether a config update payload matches the supported API shape."""
    return isinstance(raw_value, dict) and "value" in raw_value and "type" in raw_value


def _has_required_value(value: Any) -> bool:
    """Return whether the config value counts as meaningfully configured."""
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        return bool(normalized and normalized != "false")
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        return len(value) > 0
    return True


def _parse_signal_settings(raw_value: Any) -> dict[str, Any]:
    """Return normalized signal settings payload from string or object input."""
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return json.loads(raw_value.replace("'", '"'))
        except Exception:  # noqa: BLE001 - defensive parsing for config rows.
            return {}
    return {}


def _get_config_snapshot(config: Config) -> dict[str, Any]:
    """Return a best-effort config snapshot for readiness checks."""
    snapshot = getattr(config, "snapshot", None)
    if callable(snapshot):
        return snapshot()
    return {}


def _find_live_activation_blockers(
    config_snapshot: dict[str, Any],
) -> list[dict[str, str]]:
    """Return config blockers that prevent a safe dry-run-to-live transition."""
    blockers: list[dict[str, str]] = []
    always_required_keys = [
        ("timezone", "Add a timezone."),
        ("signal", "Choose a signal source."),
        ("exchange", "Choose an exchange."),
        ("timeframe", "Choose a timeframe."),
        ("key", "Add the exchange API key."),
        ("secret", "Add the exchange API secret."),
        ("currency", "Choose a quote currency."),
        ("max_bots", "Set max bots."),
        ("bo", "Set the base order amount."),
        ("tp", "Set the take profit."),
        ("history_lookback_time", "Set the history lookback window."),
    ]

    for key, message in always_required_keys:
        if not _has_required_value(config_snapshot.get(key)):
            blockers.append({"key": key, "message": message})

    dca_enabled = bool(config_snapshot.get("dca"))
    if dca_enabled:
        dynamic_dca_enabled = bool(config_snapshot.get("dynamic_dca"))
        dca_required_keys = (
            [
                ("mstc", "Set max safety order count."),
                ("sos", "Set the first safety order deviation."),
            ]
            if dynamic_dca_enabled
            else [
                ("so", "Set the safety order amount."),
                ("mstc", "Set max safety order count."),
                ("sos", "Set the first safety order deviation."),
                ("ss", "Set the safety order step scale."),
                ("os", "Set the safety order volume scale."),
            ]
        )
        for key, message in dca_required_keys:
            if not _has_required_value(config_snapshot.get(key)):
                blockers.append({"key": key, "message": message})

    signal_name = str(config_snapshot.get("signal", "") or "").strip().lower()
    signal_settings = _parse_signal_settings(config_snapshot.get("signal_settings"))
    if signal_name == "asap" and not _has_required_value(
        config_snapshot.get("symbol_list")
    ):
        blockers.append(
            {
                "key": "symbol_list",
                "message": "Add ASAP symbols or a symbol list URL.",
            }
        )
    elif signal_name == "sym_signals":
        for key, message in [
            ("api_url", "Add the SymSignals URL."),
            ("api_key", "Add the SymSignals key."),
            ("api_version", "Add the SymSignals API version."),
        ]:
            if not _has_required_value(signal_settings.get(key)):
                blockers.append({"key": f"signal_settings.{key}", "message": message})
    elif signal_name == CSV_SIGNAL_NAME:
        if not _has_required_value(signal_settings.get("csv_source")):
            blockers.append(
                {
                    "key": "signal_settings.csv_source",
                    "message": "Add a CSV source or inline CSV payload.",
                }
            )

    return blockers


def _is_live_activation_attempt(raw_value: Any) -> bool:
    """Return whether the payload tries to disable dry run through a generic path."""
    normalized = _extract_config_update_value(raw_value)
    return str(normalized).strip().lower() in {"false", "0", "no", "off"}


def _validate_live_activation_boundary(updates: dict[str, Any]) -> str | None:
    """Return an error when generic config updates try to switch the system live."""
    raw_value = updates.get(LIVE_ACTIVATION_KEY)
    if raw_value is None:
        return None
    if _is_live_activation_attempt(raw_value):
        return LIVE_ACTIVATION_DENIED_MESSAGE
    return None


async def _validate_csv_signal_switch(
    config: Config, raw_signal_update: Any
) -> str | None:
    """Return error message if switching to csv_signal while open trades exist."""
    new_signal_raw = _extract_config_update_value(raw_signal_update)
    if not isinstance(new_signal_raw, str):
        return None

    new_signal = new_signal_raw.strip()
    if not new_signal or new_signal.lower() != CSV_SIGNAL_NAME:
        return None

    current_signal = str(config.get("signal", "") or "").strip().lower()
    if current_signal == CSV_SIGNAL_NAME:
        return None

    open_trade_count = await OpenTrades.all().count()
    if open_trade_count > 0:
        return (
            "Cannot switch signal plugin to 'csv_signal' while open trades exist. "
            "Close all open trades first."
        )
    return None


@get(path="/config/all")
async def get_config() -> Any:
    """Return the current configuration as JSON.

    Returns:
        JSON response containing the full configuration cache.
    """
    config = await Config.instance()
    return config.snapshot()


@get(path="/config/freshness")
async def get_config_freshness() -> Any:
    """Return the latest config update timestamp for stale-client detection."""
    latest_row = await AppConfig.all().order_by("-updated_at").first()
    return {
        "updated_at": latest_row.updated_at.isoformat() if latest_row else None,
    }


@get(path="/config/backup/export")
async def export_backup(include_trade_data: bool = False) -> Any:
    """Export config backup with optional trade data."""
    return await backup_service.export_backup(include_trade_data)


@get(path="/config/single/{key:str}")
async def get_config_key(key: str) -> Any:
    """Get a specific config value.

    Args:
        key: Configuration key to retrieve.

    Returns:
        JSON response with the config value, or 404 if not found.
    """
    config = await Config.instance()
    value = config.get(key)
    if value is None:
        return json_response({"error": "Key not found"}, 404)
    return {key: value}


@put(path="/config/single/{key:str}")
async def update_config_key(key: str, request: Request[Any, Any, Any]) -> Any:
    """Update a specific config key via JSON body.

    Args:
        key: Configuration key to update.

    Request body:
        {"value": {"value": new_value, "type": "str|bool|int|float"}}

    Returns:
        JSON response with success/error status.
    """
    try:
        data = await request.json()
    except SerializationException:
        return json_response({"error": "Payload must be a JSON object"}, 400)
    if not isinstance(data, dict):
        return json_response({"error": "Payload must be a JSON object"}, 400)
    if "value" not in data:
        return json_response({"error": "Missing 'value' in request"}, 400)

    value = data["value"]
    if not _is_config_update_payload(value):
        return json_response(
            {"error": "Config value must be an object with 'value' and 'type'."},
            400,
        )

    config = await Config.instance()
    if key == "signal":
        error_message = await _validate_csv_signal_switch(config, value)
        if error_message:
            return json_response(
                {"error": error_message, "message": error_message}, 409
            )
    if key == LIVE_ACTIVATION_KEY:
        error_message = _validate_live_activation_boundary({key: value})
        if error_message:
            return json_response(
                {"error": error_message, "message": error_message},
                409,
            )

    # Save to DB and trigger Pub/Sub
    success = await config.set(key, value)
    if success:
        return {"message": f"Config '{key}' updated", "value": value}
    else:
        return json_response({"error": "Update failed - check config.log"}, 400)


@post(path="/config/multiple")
async def update_multiple_config_keys(request: Request[Any, Any, Any]) -> Any:
    """Update multiple config keys via JSON body.

    Request body:
        {
            "key1": {"value": new_value, "type": "str|bool|int|float"},
            "key2": {"value": new_value, "type": "str|bool|int|float"},
            ...
        }

    Returns:
        JSON response with success/error status.
    """
    try:
        data = await request.json()
    except SerializationException:
        return json_response({"error": "'data' must be a JSON object"}, 400)

    if not isinstance(data, dict):
        return json_response({"error": "'data' must be a JSON object"}, 400)
    invalid_keys = [
        key for key, value in data.items() if not _is_config_update_payload(value)
    ]
    if invalid_keys:
        invalid_key_list = ", ".join(sorted(invalid_keys))
        return json_response(
            {
                "error": (
                    "Config updates must be objects with 'value' and 'type'. "
                    f"Invalid keys: {invalid_key_list}"
                )
            },
            400,
        )

    config = await Config.instance()
    if "signal" in data:
        error_message = await _validate_csv_signal_switch(config, data["signal"])
        if error_message:
            return json_response(
                {"error": error_message, "message": error_message}, 409
            )
    error_message = _validate_live_activation_boundary(data)
    if error_message:
        return json_response({"error": error_message, "message": error_message}, 409)

    success = await config.batch_set(data)

    if success:
        return {"message": "Config updated"}
    else:
        return json_response({"error": "Update failed - check config.log"}, 400)


@post(path="/config/live/activate")
async def activate_live_trading(request: Request[Any, Any, Any]) -> Any:
    """Switch the instance from dry run to live mode after server-side checks."""
    try:
        data = await request.json()
    except SerializationException:
        data = {}

    if data is None:
        data = {}
    if not isinstance(data, dict):
        return json_response({"error": "Payload must be a JSON object"}, 400)

    confirm = bool(data.get("confirm", False))
    if not confirm:
        return json_response(
            {
                "error": "Live activation requires an explicit confirm flag.",
                "message": "Live activation requires an explicit confirm flag.",
            },
            400,
        )

    config = await Config.instance()
    config_snapshot = _get_config_snapshot(config)
    blockers = _find_live_activation_blockers(config_snapshot)

    if blockers:
        logging.warning(
            "Blocked live activation attempt with %s blocker(s): %s",
            len(blockers),
            ", ".join(blocker["key"] for blocker in blockers),
        )
        return json_response(
            {
                "error": "Live activation blocked until setup is complete.",
                "message": "Live activation blocked until setup is complete.",
                "blockers": blockers,
            },
            409,
        )

    if not bool(config_snapshot.get(LIVE_ACTIVATION_KEY, True)):
        logging.info("Live activation skipped because live trading is already active.")
        return {
            "message": "Live trading is already active.",
            "already_live": True,
        }

    success = await config.set(
        LIVE_ACTIVATION_KEY,
        {"value": False, "type": "bool"},
    )
    if not success:
        logging.error("Live activation failed during config persistence.")
        return json_response(
            {"error": "Live activation failed - check config.log"},
            400,
        )

    logging.info("Live activation succeeded.")
    return {
        "message": "Live trading activated.",
        "already_live": False,
    }


@post(path="/config/backup/restore")
async def restore_backup(request: Request[Any, Any, Any]) -> Any:
    """Restore config-only or full backup payloads."""
    try:
        data = await request.json()
    except SerializationException:
        return json_response({"error": "Payload must be a JSON object"}, 400)

    if not isinstance(data, dict):
        return json_response({"error": "Payload must be a JSON object"}, 400)

    backup_payload = data.get("backup")
    restore_trade_data = bool(data.get("restore_trade_data", False))
    if not isinstance(backup_payload, dict):
        return json_response({"error": "Missing backup payload."}, 400)

    try:
        summary = await backup_service.restore_backup(
            backup_payload,
            restore_trade_data=restore_trade_data,
        )
    except ValueError as exc:
        return json_response({"error": str(exc)}, 400)
    except Exception as exc:  # noqa: BLE001 - surface restore failures to UI.
        logging.error("Backup restore failed: %s", exc, exc_info=True)
        return json_response({"error": "Backup restore failed."}, 500)

    restored_scope = "full backup" if restore_trade_data else "configuration"
    return {
        "message": f"Restored {restored_scope} successfully.",
        "result": summary,
    }


route_handlers = [
    get_config,
    get_config_freshness,
    export_backup,
    get_config_key,
    update_config_key,
    update_multiple_config_keys,
    activate_live_trading,
    restore_backup,
]
