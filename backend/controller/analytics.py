"""Analytics API endpoints."""

from typing import Any

import helper
from litestar.exceptions import ValidationException
from litestar.handlers import get
from litestar.params import FromQuery
from service.runtime_services import runtime_service_proxy

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_analytics")

analytics = runtime_service_proxy("analytics")


@get(path="/analytics/overview")
async def analytics_overview(mode: FromQuery[str | None] = None) -> dict[str, Any]:
    """Return aggregated analytics overview for closed trades."""
    if mode not in (None, "dynamic_dca", "unknown"):
        raise ValidationException("Unsupported analytics mode.")
    return (
        await analytics.get_overview(mode) if mode else await analytics.get_overview()
    )


route_handlers = [analytics_overview]
