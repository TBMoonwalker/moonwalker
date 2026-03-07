"""Trade API endpoints."""

import asyncio
import inspect
import json
from collections.abc import AsyncGenerator
from typing import Any

import helper
from controller.responses import json_response
from litestar.connection import Request
from litestar.handlers import get, post, websocket_stream
from service.config import Config
from service.trades import Trades
from service.websocket_fanout import WebSocketFanout

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


async def _build_open_trades_payload() -> str:
    """Build serialized payload for open-trades stream."""
    output = await _get_open_trades_cached()
    return _json_dumps(output)


async def _build_closed_trades_payload() -> str:
    """Build serialized payload for closed-trades stream."""
    output = await _get_closed_trades_cached()
    return _json_dumps(output)


_open_trades_fanout = WebSocketFanout(
    name="open_trades",
    interval_seconds=5,
    producer=_build_open_trades_payload,
    logger=logging,
)
_closed_trades_fanout = WebSocketFanout(
    name="closed_trades",
    interval_seconds=5,
    producer=_build_closed_trades_payload,
    logger=logging,
)


async def start_websocket_fanout() -> None:
    """Start shared websocket fan-out workers for trades streams."""
    await _open_trades_fanout.start()
    await _closed_trades_fanout.start()


async def stop_websocket_fanout() -> None:
    """Stop shared websocket fan-out workers for trades streams."""
    await _open_trades_fanout.stop()
    await _closed_trades_fanout.stop()


@websocket_stream(path="/trades/open", warn_on_data_discard=False)
async def open_trades() -> AsyncGenerator[str, None]:
    """WebSocket endpoint for streaming open trades data every 5 seconds."""
    try:
        async for output in _open_trades_fanout.subscribe():
            yield output
    except asyncio.CancelledError:
        logging.info("Client disconnected from open trades WebSocket")
        return
    except Exception as exc:  # noqa: BLE001 - Keep stream alive diagnostics.
        logging.error("Error in open_trades WebSocket: %s", exc, exc_info=True)
        raise


@websocket_stream(path="/trades/closed", warn_on_data_discard=False)
async def closed_trades() -> AsyncGenerator[str, None]:
    """WebSocket endpoint for streaming closed trades data every 5 seconds."""
    try:
        async for output in _closed_trades_fanout.subscribe():
            yield output
    except asyncio.CancelledError:
        logging.info("Client disconnected from closed trades WebSocket")
        return
    except Exception as exc:  # noqa: BLE001 - Keep stream alive diagnostics.
        logging.error("Error in closed_trades WebSocket: %s", exc, exc_info=True)
        raise


@get(path="/trades/closed/length")
async def closed_trades_length() -> dict[str, Any]:
    """Get the count of closed trades."""
    response = await trades.get_closed_trades_length()
    return {"result": response}


@get(path="/trades/closed/{page:str}")
async def closed_trades_pagination(page: str) -> dict[str, Any]:
    """Get paginated closed trades data."""
    response = await trades.get_closed_trades(int(page))
    return {"result": response}


@post(path="/trades/closed/delete/{trade_id:str}")
async def closed_trade_delete(trade_id: str) -> Any:
    """Delete a closed trade by ID."""
    try:
        trade_identifier = int(trade_id)
    except ValueError:
        return json_response({"result": "", "error": "Invalid trade id."}, 400)

    deleted = await trades.delete_closed_trade(trade_identifier)
    if deleted:
        return {"result": "deleted"}
    return json_response({"result": "", "error": "Trade not found."}, 404)


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


@post(path="/trades/import/csv")
async def import_open_trades_csv(request: Request[Any, Any, Any]) -> Any:
    """Import open trades from CSV content."""
    try:
        form = await request.form()
        csv_file = form.get("file")
        if csv_file is None:
            return json_response(
                {"result": "", "error": "Missing file field 'file'."}, 400
            )

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
        return {"result": "ok", **result}
    except ValueError as exc:
        return json_response({"result": "", "error": str(exc)}, 400)
    except Exception as exc:  # noqa: BLE001 - Keep API resilient on import errors.
        logging.error("Failed importing trades from CSV: %s", exc, exc_info=True)
        return json_response({"result": "", "error": "Failed importing CSV."}, 500)


route_handlers = [
    open_trades,
    closed_trades,
    closed_trades_length,
    closed_trades_pagination,
    closed_trade_delete,
    import_open_trades_csv,
]
