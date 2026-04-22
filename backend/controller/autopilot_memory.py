"""Autopilot memory cockpit endpoints."""

from typing import Any

from litestar.handlers import get
from service.autopilot_memory import AutopilotMemoryService


@get(path="/autopilot/memory")
async def autopilot_memory() -> dict[str, Any]:
    """Return the persisted Autopilot memory cockpit read model."""
    service = await AutopilotMemoryService.instance()
    return service.build_read_model()


route_handlers = [autopilot_memory]
