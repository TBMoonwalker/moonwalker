"""Configuration API endpoints."""

import json
from typing import Any

import helper
from controller.responses import json_response
from litestar.connection import Request
from litestar.handlers import get, post, put
from model import OpenTrades
from service.config import Config

logging = helper.LoggerFactory.get_logger("logs/config.log", "config_data")

CSV_SIGNAL_NAME = "csv_signal"


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
    except Exception:  # noqa: BLE001 - Return explicit validation error payload.
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
    except Exception:  # noqa: BLE001 - Return explicit validation error payload.
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


route_handlers = [
    get_config,
    get_config_key,
    update_config_key,
    update_multiple_config_keys,
]
