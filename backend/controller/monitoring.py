"""Monitoring API endpoints."""

from typing import Any

import helper
from controller.responses import json_response
from litestar.connection import Request
from litestar.exceptions import SerializationException
from litestar.handlers import post
from service.config import Config
from service.monitoring import MonitoringService

logging = helper.LoggerFactory.get_logger(
    "logs/controller.log", "controller_monitoring"
)


@post(path="/monitoring/test")
async def test_monitoring_telegram(request: Request[Any, Any, Any]) -> Any:
    """Send a monitoring test message to Telegram."""
    try:
        payload = await request.json()
    except SerializationException:
        payload = {}
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return json_response({"error": "Payload must be a JSON object."}, 400)

    config = await Config.instance()
    effective_config = config.snapshot()
    effective_config.update(payload)

    monitoring_service = MonitoringService()
    success, message = await monitoring_service.send_test_notification(effective_config)
    if not success:
        return json_response({"error": message}, 400)
    return {"message": message}


route_handlers = [test_monitoring_telegram]
