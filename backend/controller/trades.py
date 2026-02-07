import asyncio
from typing import Any

import helper
from quart import websocket
from quart_cors import route_cors

from controller import controller
from service.trades import Trades

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_trades")
trades = Trades()


@controller.websocket("/trades/open")
async def open_trades() -> None:
    """WebSocket endpoint for streaming open trades data.

    Sends open trades data to connected clients every 5 seconds.

    Raises:
        asyncio.CancelledError: When client disconnects.
    """
    try:
        while True:
            output = await trades.get_open_trades()
            await websocket.send(output)
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Handle disconnection gracefully
        logging.info("Client disconnected from open trades WebSocket")
        raise
    except Exception as exc:  # noqa: BLE001 - Catch all exceptions to prevent WebSocket hang
        logging.error("Error in open_trades WebSocket: %s", exc, exc_info=True)
        raise


@controller.websocket("/trades/closed")
async def closed_trades() -> None:
    """WebSocket endpoint for streaming closed trades data.

    Sends closed trades data to connected clients every 5 seconds.

    Raises:
        asyncio.CancelledError: When client disconnects.
    """
    try:
        while True:
            output = await trades.get_closed_trades()
            await websocket.send(output)
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Handle disconnection gracefully
        logging.info("Client disconnected from closed trades WebSocket")
        raise
    except Exception as exc:  # noqa: BLE001 - Catch all exceptions to prevent WebSocket hang
        logging.error("Error in closed_trades WebSocket: %s", exc, exc_info=True)
        raise


@controller.route("/trades/closed/length")
@route_cors(
    allow_methods=["GET"],
    allow_origin=["*"],
)
async def closed_trades_length() -> dict[str, Any]:
    """Get the count of closed trades.

    Returns:
        Dictionary with the count of closed trades.

    Example:
        {"result": 42}
    """
    response = await trades.get_closed_trades_length()
    if not response:
        response = {"result": ""}

    return response


@controller.route("/trades/closed/<page>")
@route_cors(
    allow_methods=["GET"],
    allow_origin=["*"],
)
async def closed_trades_pagination(page: str) -> dict[str, Any]:
    """Get paginated closed trades data.

    Args:
        page: Page number to retrieve.

    Returns:
        Dictionary with closed trades data for the requested page.

    Example:
        {"result": [...]} or {"result": ""}
    """
    response = await trades.get_closed_trades(int(page))
    if not response:
        response = {"result": ""}

    return response
