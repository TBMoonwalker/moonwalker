import helper
from controller import controller
from quart_cors import route_cors
from quart import request, jsonify
from service.config import Config

logging = helper.LoggerFactory.get_logger("logs/config.log", "config_data")


@controller.route("/config/all", methods=["GET"])
@route_cors(allow_origin="*")
async def get_config():
    """
    Return the current configuration as JSON
    """
    config = await Config.instance()
    return jsonify(config._cache)


@controller.route("/config/single/<string:key>", methods=["GET"])
@route_cors(allow_origin="*")
async def get_config_key(key: str):
    """
    Get a specific config value
    """
    config = await Config.instance()
    value = config.get(key)
    if value is None:
        return jsonify({"error": "Key not found"}), 404
    return jsonify({key: value})


@controller.route("/config/single/<string:key>", methods=["PUT"])
@route_cors(allow_origin="*")
async def update_config_key(key: str):
    """
    Update a specific config key via JSON body: {"value": ...}
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
async def update_multiple_config_keys():
    """
    Update multiple config keys via JSON body: {"key1": "value1", "key2": "value2", ...}
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