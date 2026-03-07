"""Statistics API endpoints."""

import asyncio
import json
from typing import Any

import helper
from controller import controller
from quart import websocket
from quart_cors import route_cors
from service.config import Config
from service.exchange import Exchange
from service.statistic import Statistic

logging = helper.LoggerFactory.get_logger(
    "logs/controller.log", "controller_statistics"
)

statistic = Statistic()
exchange = Exchange()
_config_service: Config | None = None


async def _get_config_service() -> Config:
    """Return cached Config singleton reference."""
    global _config_service
    if _config_service is None:
        _config_service = await Config.instance()
    return _config_service


async def _get_available_funds() -> float | None:
    """Resolve available quote funds from the configured exchange account."""
    try:
        config_service = await _get_config_service()
        currency = str(config_service.get("currency", "USDC")).strip().upper()
        if not currency:
            return None
        return await exchange.get_free_balance_for_asset(
            config_service._cache, currency
        )
    except Exception as exc:  # noqa: BLE001 - Avoid breaking stats websocket updates.
        logging.warning("Failed to fetch available exchange funds: %s", exc)
        return None


@helper.async_ttl_cache(maxsize=1, ttl=2)
async def _get_profit_cached() -> dict[str, Any]:
    profit = await statistic.get_profit()
    profit["funds_available"] = await _get_available_funds()
    return profit


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
