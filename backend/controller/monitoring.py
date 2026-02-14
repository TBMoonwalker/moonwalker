"""Monitoring API endpoints."""

from typing import Any

import helper
from controller import controller
from quart import jsonify, request
from quart_cors import route_cors
from service.config import Config
from service.monitoring import MonitoringService

logging = helper.LoggerFactory.get_logger(
    "logs/controller.log", "controller_monitoring"
)


@controller.route("/monitoring/test", methods=["POST"])
@route_cors(allow_origin="*")
async def test_monitoring_webhook() -> tuple[Any, int]:
    """Send a monitoring test message to the configured webhook."""
    payload = await request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Payload must be a JSON object."}), 400

    config = await Config.instance()
    effective_config = dict(config._cache)
    effective_config.update(payload)

    monitoring_service = MonitoringService()
    success, message = await monitoring_service.send_test_notification(effective_config)
    if not success:
        return jsonify({"error": message}), 400
    return jsonify({"message": message}), 200
