"""Analytics API endpoints."""

from typing import Any

import helper
from litestar.handlers import get
from service.runtime_services import runtime_service_proxy

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_analytics")

analytics = runtime_service_proxy("analytics")


@get(path="/analytics/overview")
async def analytics_overview() -> dict[str, Any]:
    """Return aggregated analytics overview for closed trades."""
    return await analytics.get_overview()


route_handlers = [analytics_overview]
