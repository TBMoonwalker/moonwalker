"""Statistics API endpoints."""

import asyncio
import json
from typing import Any

import helper
from quart import websocket
from quart_cors import route_cors

from controller import controller
from service.statistic import Statistic

logging = helper.LoggerFactory.get_logger(
    "logs/controller.log", "controller_statistics"
)

statistic = Statistic()


@controller.websocket("/statistic/profit")
async def profit() -> None:
    """WebSocket endpoint for streaming profit statistics.

    Sends profit data to connected clients every 5 seconds.

    Raises:
        asyncio.CancelledError: When client disconnects.
    """
    try:
        while True:
            output = json.dumps(await statistic.get_profit())
            await websocket.send(output)
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Handle disconnection gracefully
        logging.info("Client disconnected from profit WebSocket")
        raise
    except (
        Exception
    ) as exc:  # noqa: BLE001 - Catch all exceptions to prevent WebSocket hang
        logging.error("Error in profit WebSocket: %s", exc, exc_info=True)
        raise


@controller.route("/statistic/profit/<timestamp>/<period>")
@route_cors(
    allow_methods=["GET"],
    allow_origin=["*"],
)
async def profit_statistics(timestamp: str, period: str) -> str | dict[str, Any]:
    """Get profit statistics for a specific time period.

    Args:
        timestamp: Start timestamp for the query.
        period: Time period for the query.

    Returns:
        JSON string with profit statistics, or empty dict if no data.

    Example:
        {"result": "..."} or {"result": ""}
    """
    response = json.dumps(await statistic.get_profits_overall(timestamp, period))
    if not response:
        response = {"result": ""}

    return response
