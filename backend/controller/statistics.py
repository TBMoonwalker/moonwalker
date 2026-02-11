"""Statistics API endpoints."""

import asyncio
import json
from typing import Any

import helper
from controller import controller
from quart import websocket
from quart_cors import route_cors
from service.statistic import Statistic

logging = helper.LoggerFactory.get_logger(
    "logs/controller.log", "controller_statistics"
)

statistic = Statistic()


@helper.async_ttl_cache(maxsize=1, ttl=2)
async def _get_profit_cached() -> dict[str, Any]:
    return await statistic.get_profit()


@controller.websocket("/statistic/profit")
async def profit() -> None:
    """WebSocket endpoint for streaming profit statistics.

    Sends profit data to connected clients every 5 seconds.

    Raises:
        asyncio.CancelledError: When client disconnects.
    """
    try:
        while True:
            output = json.dumps(await _get_profit_cached())
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


@controller.route("/statistic/upnl/all")
@route_cors(
    allow_methods=["GET"],
    allow_origin=["*"],
)
async def upnl_statistics_all() -> str | dict[str, Any]:
    """Get full uPNL history from the beginning."""
    response = json.dumps(await statistic.get_upnl_history_all())
    if not response:
        response = {"result": ""}

    return response


@controller.route("/statistic/profit-overall/timeline")
@route_cors(
    allow_methods=["GET"],
    allow_origin=["*"],
)
async def profit_overall_timeline() -> str | dict[str, Any]:
    """Get last-12-month profit-overall timeline with adaptive resolution."""
    response = json.dumps(await statistic.get_profit_overall_timeline())
    if not response:
        response = {"result": ""}

    return response
