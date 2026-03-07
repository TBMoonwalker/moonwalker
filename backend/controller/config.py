"""Configuration API endpoints."""

from typing import Any

import helper
from controller.responses import json_response
from litestar.connection import Request
from litestar.handlers import get, post, put
from service.config import Config

logging = helper.LoggerFactory.get_logger("logs/config.log", "config_data")


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

    value = data["value"]
    # Save to DB and trigger Pub/Sub
    config = await Config.instance()
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
