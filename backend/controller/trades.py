"""Trade API endpoints."""

import asyncio
import inspect
import json
from typing import Any

import helper
from controller import controller
from quart import jsonify, request, websocket
from quart_cors import route_cors
from service.config import Config
from service.trades import Trades

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_trades")
trades = Trades()


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, default=str)


@helper.async_ttl_cache(maxsize=1, ttl=2)
async def _get_open_trades_cached() -> list[dict[str, Any]]:
    return await trades.get_open_trades()


@helper.async_ttl_cache(maxsize=1, ttl=2)
async def _get_closed_trades_cached() -> list[dict[str, Any]]:
    return await trades.get_closed_trades()


@controller.websocket("/trades/open")
async def open_trades() -> None:
    """WebSocket endpoint for streaming open trades data.

    Sends open trades data to connected clients every 5 seconds.

    Raises:
        asyncio.CancelledError: When client disconnects.
    """
    try:
        while True:
            output = await _get_open_trades_cached()
            await websocket.send(_json_dumps(output))
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Handle disconnection gracefully
        logging.info("Client disconnected from open trades WebSocket")
        raise
    except (
        Exception
    ) as exc:  # noqa: BLE001 - Catch all exceptions to prevent WebSocket hang
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
            output = await _get_closed_trades_cached()
            await websocket.send(_json_dumps(output))
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Handle disconnection gracefully
        logging.info("Client disconnected from closed trades WebSocket")
        raise
    except (
        Exception
    ) as exc:  # noqa: BLE001 - Catch all exceptions to prevent WebSocket hang
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
    return {"result": response}


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
    return {"result": response}


@controller.route("/trades/closed/delete/<trade_id>", methods=["POST"])
@route_cors(
    allow_methods=["POST"],
    allow_origin=["*"],
)
async def closed_trade_delete(trade_id: str) -> Any:
    """Delete a closed trade by ID."""
    try:
        trade_identifier = int(trade_id)
    except ValueError:
        return jsonify({"result": "", "error": "Invalid trade id."}), 400

    deleted = await trades.delete_closed_trade(trade_identifier)
    if deleted:
        return jsonify({"result": "deleted"})
    return jsonify({"result": "", "error": "Trade not found."}), 404


async def _read_upload_as_text(upload: Any) -> str:
    """Read an uploaded file object and return UTF-8 text."""
    raw_content = upload.read()
    if inspect.isawaitable(raw_content):
        raw_content = await raw_content

    if isinstance(raw_content, bytes):
        return raw_content.decode("utf-8-sig")
    if isinstance(raw_content, str):
        return raw_content
    return ""


@controller.route("/trades/import/csv", methods=["POST"])
@route_cors(
    allow_methods=["POST"],
    allow_origin=["*"],
)
async def import_open_trades_csv() -> Any:
    """Import open trades from CSV content."""
    try:
        files = await request.files
        csv_file = files.get("file")
        if csv_file is None:
            return jsonify({"result": "", "error": "Missing file field 'file'."}), 400

        form = await request.form
        overwrite_raw = str(form.get("overwrite", "false")).strip().lower()
        overwrite = overwrite_raw in {"1", "true", "yes", "on"}

        csv_content = await _read_upload_as_text(csv_file)
        config = await Config.instance()
        quote_currency = str(config.get("currency", "USDT")).upper().strip()
        take_profit = float(config.get("take_profit", 0.0) or 0.0)
        first_so_deviation = float(config.get("sos", 0.0) or 0.0)
        safety_step_scale = float(config.get("ss", 1.0) or 1.0)

        result = await trades.import_open_trades_from_csv(
            csv_content=csv_content,
            quote_currency=quote_currency,
            take_profit=take_profit,
            first_so_deviation=first_so_deviation,
            safety_step_scale=safety_step_scale,
            overwrite=overwrite,
        )
        return jsonify({"result": "ok", **result})
    except ValueError as exc:
        return jsonify({"result": "", "error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 - Keep API resilient on import errors.
        logging.error("Failed importing trades from CSV: %s", exc, exc_info=True)
        return jsonify({"result": "", "error": "Failed importing CSV."}), 500
