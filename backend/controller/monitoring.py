"""Monitoring API endpoints."""

import asyncio
from typing import Any

import helper
from controller.responses import json_response
from litestar.connection import Request
from litestar.exceptions import SerializationException
from litestar.handlers import get, post
from service.config import Config
from service.log_viewer import LogViewerService
from service.monitoring import MonitoringService

logging = helper.LoggerFactory.get_logger(
    "logs/controller.log", "controller_monitoring"
)
log_viewer_service = LogViewerService()


@get(path="/monitoring/logs")
async def get_monitoring_log_sources() -> Any:
    """Return available log sources for the monitoring UI."""
    sources = await asyncio.to_thread(log_viewer_service.list_sources)
    return {"sources": sources}


@get(path="/monitoring/logs/{source:str}")
async def get_monitoring_log_source(
    source: str,
    cursor: int | None = None,
    before: int | None = None,
    limit: int = 200,
) -> Any:
    """Return tailed or backfilled lines for a monitoring log source."""
    try:
        result = await asyncio.to_thread(
            log_viewer_service.read_source,
            source,
            cursor,
            before,
            limit,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "Unknown log source" in message else 400
        return json_response({"error": message}, status_code)
    return result.to_dict()


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


route_handlers = [
    get_monitoring_log_sources,
    get_monitoring_log_source,
    test_monitoring_telegram,
]
