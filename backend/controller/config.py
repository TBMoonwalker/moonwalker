"""Configuration API endpoints."""

import json
from typing import Any

import helper
from controller.responses import json_response
from litestar.connection import Request
from litestar.exceptions import SerializationException
from litestar.handlers import get, post, put
from model import OpenTrades
from service.backup_restore import BackupService
from service.config import Config

logging = helper.LoggerFactory.get_logger("logs/config.log", "config_data")

CSV_SIGNAL_NAME = "csv_signal"
backup_service = BackupService()


def _extract_config_update_value(raw_value: Any) -> Any:
    """Extract normalized `value` from config update payloads."""
    parsed = raw_value
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return parsed
    if isinstance(parsed, dict) and "value" in parsed:
        return parsed["value"]
    return parsed


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
    return config._cache


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
        {"value": new_value}

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

    config = await Config.instance()
    value = data["value"]

    if key == "signal":
        error_message = await _validate_csv_signal_switch(config, value)
        if error_message:
            return json_response(
                {"error": error_message, "message": error_message}, 409
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
        {"key1": "value1", "key2": "value2", ...}

    Returns:
        JSON response with success/error status.
    """
    try:
        data = await request.json()
    except SerializationException:
        return json_response({"error": "'data' must be a JSON object"}, 400)

    if not isinstance(data, dict):
        return json_response({"error": "'data' must be a JSON object"}, 400)

    config = await Config.instance()
    if "signal" in data:
        error_message = await _validate_csv_signal_switch(config, data["signal"])
        if error_message:
            return json_response(
                {"error": error_message, "message": error_message}, 409
            )

    success = await config.batch_set(data)

    if success:
        return {"message": "Config updated"}
    else:
        return json_response({"error": "Update failed - check config.log"}, 400)


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
    export_backup,
    get_config_key,
    update_config_key,
    update_multiple_config_keys,
    restore_backup,
]
