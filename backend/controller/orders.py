"""Order API endpoints."""

from typing import Any

import helper
from litestar.handlers import get
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


route_handlers = [sell_order, buy_order, stop_order]
