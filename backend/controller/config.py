from typing import Any

import helper
from quart import jsonify, request
from quart_cors import route_cors

from controller import controller
from service.config import Config

logging = helper.LoggerFactory.get_logger("logs/config.log", "config_data")


@controller.route("/config/all", methods=["GET"])
@route_cors(allow_origin="*")
async def get_config() -> Any:
    """Return the current configuration as JSON.

    Returns:
        JSON response containing the full configuration cache.
    """
    config = await Config.instance()
    return jsonify(config._cache)


@controller.route("/config/single/<string:key>", methods=["GET"])
@route_cors(allow_origin="*")
async def get_config_key(key: str) -> tuple[Any, int]:
    """Get a specific config value.

    Args:
        key: Configuration key to retrieve.

    Returns:
        JSON response with the config value, or 404 if not found.
    """
    config = await Config.instance()
    value = config.get(key)
    if value is None:
        return jsonify({"error": "Key not found"}), 404
    return jsonify({key: value})


@controller.route("/config/single/<string:key>", methods=["PUT"])
@route_cors(allow_origin="*")
async def update_config_key(key: str) -> tuple[Any, int]:
    """Update a specific config key via JSON body.

    Args:
        key: Configuration key to update.

    Request body:
        {"value": new_value}

    Returns:
        JSON response with success/error status.
    """
    data = await request.get_json()
    if "value" not in data:
        return jsonify({"error": "Missing 'value' in request"}), 400

    value = data["value"]
    # Save to DB and trigger Pub/Sub
    config = await Config.instance()
    success = await config.set(key, value)
    if success:
        return jsonify({"message": f"Config '{key}' updated", "value": value})
    else:
        return jsonify({"error": "Update failed - check config.log"}), 400

@controller.route("/config/multiple", methods=["POST"])
@route_cors(allow_origin="*")
async def update_multiple_config_keys() -> tuple[Any, int]:
    """Update multiple config keys via JSON body.

    Request body:
        {"key1": "value1", "key2": "value2", ...}

    Returns:
        JSON response with success/error status.
    """
    data = await request.get_json()

    if not isinstance(data, dict):
        return jsonify({"error": "'data' must be a JSON object"}), 400

    # Initialize the response
    response = {"updated": []}

    config = await Config.instance()
    success = await config.batch_set(data)

    if success:
        return jsonify({"message": f"Config updated"})
    else:
        return jsonify({"error": "Update failed - check config.log"}), 400