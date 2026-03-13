"""Order API endpoints."""

from typing import Any

import helper
from controller.responses import json_response
from litestar.connection import Request
from litestar.exceptions import SerializationException
from litestar.handlers import get, post
from service.config import Config
from service.orders import Orders

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_orders")
orders = Orders()


@get(path="/orders/sell/{symbol:str}")
async def sell_order(symbol: str) -> dict[str, Any]:
    """Create a sell order for the specified symbol.

    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT").

    Returns:
        Dictionary with result status.

    Example:
        {"result": "sell"} or {"result": ""}
    """
    config = await Config.instance()
    if await orders.receive_sell_signal(symbol, config):
        return {"result": "sell"}
    else:
        return {"result": ""}


@get(path="/orders/buy/{symbol:str}/{ordersize:str}")
async def buy_order(symbol: str, ordersize: str) -> dict[str, Any]:
    """Create a buy order for the specified symbol and size.

    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT").
        ordersize: Order size in quote currency.

    Returns:
        Dictionary with result status.

    Example:
        {"result": "new_so"} or {"result": ""}
    """
    config = await Config.instance()
    if await orders.receive_buy_signal(symbol, ordersize, config):
        return {"result": "new_so"}
    else:
        return {"result": ""}


@get(path="/orders/stop/{symbol:str}")
async def stop_order(symbol: str) -> dict[str, Any]:
    """Stop an active order for the specified symbol.

    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT").

    Returns:
        Dictionary with result status.

    Example:
        {"result": "stop"} or {"result": ""}
    """
    if await orders.receive_stop_signal(symbol):
        return {"result": "stop"}
    else:
        return {"result": ""}


@post(path="/orders/buy/manual")
async def add_manual_buy(request: Request[Any, Any, Any]) -> Any:
    """Append a manual buy row without placing an exchange order."""
    try:
        payload = await request.json()
    except SerializationException:
        return json_response(
            {"result": "", "error": "Payload must be a JSON object"}, 400
        )

    if not isinstance(payload, dict):
        return json_response(
            {"result": "", "error": "Payload must be a JSON object"}, 400
        )

    required_keys = ("symbol", "date", "price", "amount")
    missing = [key for key in required_keys if key not in payload]
    if missing:
        return json_response(
            {"result": "", "error": f"Missing required fields: {', '.join(missing)}"},
            400,
        )

    config = await Config.instance()
    try:
        result = await orders.receive_manual_buy_add(
            symbol=str(payload.get("symbol", "")),
            date_input=payload.get("date"),
            price_raw=payload.get("price"),
            amount_raw=payload.get("amount"),
            config=config,
        )
    except ValueError as exc:
        return json_response({"result": "", "error": str(exc)}, 400)

    return {"result": "manual_so", "data": result}


route_handlers = [sell_order, buy_order, stop_order, add_manual_buy]
