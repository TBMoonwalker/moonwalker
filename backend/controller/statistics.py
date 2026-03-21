"""Statistics API endpoints."""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import helper
from litestar.exceptions import WebSocketDisconnect
from litestar.handlers import get, websocket_stream
from service.config import Config
from service.exchange import Exchange
from service.statistic import Statistic
from service.websocket_fanout import WebSocketFanout

logging = helper.LoggerFactory.get_logger(
    "logs/controller.log", "controller_statistics"
)
PROFIT_STREAM_INTERVAL_SECONDS = 5
STATISTICS_BALANCE_CACHE_TTL_SECONDS = float(PROFIT_STREAM_INTERVAL_SECONDS)

statistic = Statistic()
exchange = Exchange(balance_cache_ttl_seconds=STATISTICS_BALANCE_CACHE_TTL_SECONDS)
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
            config_service.snapshot(), currency
        )
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        logging.warning("Failed to fetch available exchange funds: %s", exc)
        return None


@helper.async_ttl_cache(maxsize=1, ttl=2)
async def _get_profit_cached() -> dict[str, Any]:
    available_funds = await _get_available_funds()
    return await statistic.get_profit_for_dashboard(available_funds)


async def _build_profit_payload() -> str:
    """Build serialized payload for profit websocket stream."""
    return json.dumps(await _get_profit_cached())


_profit_fanout = WebSocketFanout(
    name="profit",
    interval_seconds=PROFIT_STREAM_INTERVAL_SECONDS,
    producer=_build_profit_payload,
    logger=logging,
)


async def start_websocket_fanout() -> None:
    """Start shared websocket fan-out worker for statistics stream."""
    await _profit_fanout.start()


async def stop_websocket_fanout() -> None:
    """Stop shared websocket fan-out worker for statistics stream."""
    await _profit_fanout.stop()


@websocket_stream(path="/statistic/profit", warn_on_data_discard=False)
async def profit() -> AsyncGenerator[str, None]:
    """WebSocket endpoint for streaming profit statistics.

    Sends profit data to connected clients every 5 seconds.

    Raises:
        asyncio.CancelledError: When client disconnects.
    """
    try:
        async for output in _profit_fanout.subscribe():
            yield output
    except (asyncio.CancelledError, WebSocketDisconnect):
        # Handle disconnection gracefully
        logging.info("Client disconnected from profit WebSocket")
        return


@get(path="/statistic/profit/{timestamp:str}/{period:str}")
async def profit_statistics(timestamp: str, period: str) -> dict[str, Any]:
    """Get profit statistics for a specific time period.

    Args:
        timestamp: Start timestamp for the query.
        period: Time period for the query.

    Returns:
        Profit statistics as JSON-serializable dictionary.

    Example:
        {"result": "..."} or {"result": ""}
    """
    response = await statistic.get_profits_overall(timestamp, period)
    if response is None:
        return {"result": ""}
    return response


@get(path="/statistic/profit-overall/timeline")
async def profit_overall_timeline() -> list[dict[str, Any]]:
    """Get last-12-month profit-overall timeline with adaptive resolution."""
    return await statistic.get_profit_overall_timeline()


route_handlers = [profit, profit_statistics, profit_overall_timeline]
