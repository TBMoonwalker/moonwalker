"""Analytics API endpoints."""

from typing import Any

import helper
from litestar.handlers import get
from service.analytics import Analytics

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_analytics")

analytics = Analytics()


@get(path="/analytics/overview")
async def analytics_overview() -> dict[str, Any]:
    """Return aggregated analytics overview for closed trades."""
    return await analytics.get_overview()


route_handlers = [analytics_overview]
