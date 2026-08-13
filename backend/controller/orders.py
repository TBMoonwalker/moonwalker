"""Order API endpoints."""

import re
from typing import Any

import helper
from controller.responses import json_response
from litestar.connection import Request
from litestar.exceptions import SerializationException
from litestar.handlers import post
from litestar.params import FromPath
from service.config import Config
from service.runtime_services import runtime_service_proxy

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_orders")
orders = runtime_service_proxy("orders")
OPERATION_ID_HEADER = "x-moonwalker-operation-id"
OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def _operation_id_from_request(request: Request[Any, Any, Any]) -> str | None:
    """Validate an optional client identity for one confirmed operator action."""
    operation_id = str(request.headers.get(OPERATION_ID_HEADER) or "").strip()
    if not operation_id:
        return None
    if not OPERATION_ID_PATTERN.fullmatch(operation_id):
        raise ValueError(
            "X-Moonwalker-Operation-Id must be 1-64 letters, numbers, or ._:-"
        )
    return operation_id


@post(path="/orders/sell/{symbol:str}", status_code=200)
async def sell_order(
    symbol: FromPath[str],
    request: Request[Any, Any, Any],
) -> Any:
    """Create a sell order for the specified symbol.

    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT").
        request: HTTP request carrying an optional durable operation ID.

    Returns:
        Legacy result status plus the typed mutation result.

    Example:
        {"result": "sell", "mutation": {"status": "applied", ...}}
    """
    config = await Config.instance()
    try:
        operation_id = _operation_id_from_request(request)
    except ValueError as exc:
        return json_response({"result": "", "error": str(exc)}, 400)
    mutation = await orders.receive_sell_signal_result(
        symbol,
        config,
        operation_id=operation_id,
    )
    return {
        "result": "sell" if mutation.applied else "",
        "mutation": mutation.to_dict(),
    }


@post(path="/orders/buy/{symbol:str}/{ordersize:str}", status_code=200)
async def buy_order(
    symbol: FromPath[str],
    ordersize: FromPath[str],
    request: Request[Any, Any, Any],
) -> Any:
    """Create a buy order for the specified symbol and size.

    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT").
        ordersize: Order size in quote currency.
        request: HTTP request carrying an optional durable operation ID.

    Returns:
        Legacy result status plus the typed mutation result.

    Example:
        {"result": "new_so", "mutation": {"status": "applied", ...}}
    """
    config = await Config.instance()
    try:
        operation_id = _operation_id_from_request(request)
    except ValueError as exc:
        return json_response({"result": "", "error": str(exc)}, 400)
    mutation = await orders.receive_buy_signal_result(
        symbol,
        ordersize,
        config,
        operation_id=operation_id,
    )
    return {
        "result": "new_so" if mutation.applied else "",
        "mutation": mutation.to_dict(),
    }


@post(path="/orders/stop/{symbol:str}", status_code=200)
async def stop_order(symbol: FromPath[str]) -> dict[str, Any]:
    """Stop an active order for the specified symbol.

    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT").

    Returns:
        Dictionary with result status.

    Example:
        {"result": "stop"} or {"result": ""}
    """
    config = await Config.instance()
    mutation = await orders.receive_stop_signal_result(symbol, config)
    return {
        "result": "stop" if mutation.applied else "",
        "mutation": mutation.to_dict(),
    }


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
