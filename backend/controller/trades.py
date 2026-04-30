"""Trade API endpoints."""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import helper
from controller.responses import json_response
from litestar.exceptions import WebSocketDisconnect
from litestar.handlers import get, post, websocket_stream
from service.spot_sidestep_campaign import SpotSidestepCampaignService
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


@helper.async_ttl_cache(maxsize=1, ttl=2)
async def _get_unsellable_trades_cached() -> list[dict[str, Any]]:
    return await trades.get_unsellable_trades()


@helper.async_ttl_cache(maxsize=1, ttl=2)
async def _get_waiting_campaigns_cached() -> list[dict[str, Any]]:
    sidestep_campaigns = await SpotSidestepCampaignService.instance()
    return await sidestep_campaigns.get_waiting_campaign_summaries()


async def _build_open_trades_payload() -> str:
    """Build serialized payload for open-trades stream."""
    output = await _get_open_trades_cached()
    return _json_dumps(output)


async def _build_closed_trades_payload() -> str:
    """Build serialized payload for closed-trades stream."""
    output = await _get_closed_trades_cached()
    return _json_dumps(output)


async def _build_unsellable_trades_payload() -> str:
    """Build serialized payload for unsellable-trades stream."""
    output = await _get_unsellable_trades_cached()
    return _json_dumps(output)


async def _build_waiting_campaigns_payload() -> str:
    """Build serialized payload for waiting-campaigns stream."""
    output = await _get_waiting_campaigns_cached()
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
_unsellable_trades_fanout = WebSocketFanout(
    name="unsellable_trades",
    interval_seconds=5,
    producer=_build_unsellable_trades_payload,
    logger=logging,
)
_waiting_campaigns_fanout = WebSocketFanout(
    name="waiting_campaigns",
    interval_seconds=5,
    producer=_build_waiting_campaigns_payload,
    logger=logging,
)


async def start_websocket_fanout() -> None:
    """Start shared websocket fan-out workers for trades streams."""
    await _open_trades_fanout.start()
    await _closed_trades_fanout.start()
    await _unsellable_trades_fanout.start()
    await _waiting_campaigns_fanout.start()


async def stop_websocket_fanout() -> None:
    """Stop shared websocket fan-out workers for trades streams."""
    await _open_trades_fanout.stop()
    await _closed_trades_fanout.stop()
    await _unsellable_trades_fanout.stop()
    await _waiting_campaigns_fanout.stop()


@websocket_stream(path="/trades/open", warn_on_data_discard=False)
async def open_trades() -> AsyncGenerator[str, None]:
    """WebSocket endpoint for streaming open trades data every 5 seconds."""
    try:
        async for output in _open_trades_fanout.subscribe():
            yield output
    except (asyncio.CancelledError, WebSocketDisconnect):
        logging.info("Client disconnected from open trades WebSocket")
        return


@websocket_stream(path="/trades/closed", warn_on_data_discard=False)
async def closed_trades() -> AsyncGenerator[str, None]:
    """WebSocket endpoint for streaming closed trades data every 5 seconds."""
    try:
        async for output in _closed_trades_fanout.subscribe():
            yield output
    except (asyncio.CancelledError, WebSocketDisconnect):
        logging.info("Client disconnected from closed trades WebSocket")
        return


@websocket_stream(path="/trades/unsellable", warn_on_data_discard=False)
async def unsellable_trades() -> AsyncGenerator[str, None]:
    """WebSocket endpoint for streaming unsellable trades data every 5 seconds."""
    try:
        async for output in _unsellable_trades_fanout.subscribe():
            yield output
    except (asyncio.CancelledError, WebSocketDisconnect):
        logging.info("Client disconnected from unsellable trades WebSocket")
        return


@websocket_stream(path="/trades/waiting", warn_on_data_discard=False)
async def waiting_campaigns() -> AsyncGenerator[str, None]:
    """WebSocket endpoint for streaming waiting-campaign summaries."""
    try:
        async for output in _waiting_campaigns_fanout.subscribe():
            yield output
    except (asyncio.CancelledError, WebSocketDisconnect):
        logging.info("Client disconnected from waiting campaigns WebSocket")
        return


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


@get(path="/trades/executions/{deal_id:str}")
async def trade_executions(deal_id: str) -> dict[str, Any]:
    """Get execution rows for one trade deal."""
    response = await trades.get_trade_executions(deal_id)
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


@post(path="/trades/unsellable/delete/{trade_id:str}")
async def unsellable_trade_delete(trade_id: str) -> Any:
    """Delete an unsellable trade by ID after manual cleanup."""
    try:
        trade_identifier = int(trade_id)
    except ValueError:
        return json_response({"result": "", "error": "Invalid trade id."}, 400)

    deleted = await trades.delete_unsellable_trade(trade_identifier)
    if deleted:
        return {"result": "deleted"}
    return json_response({"result": "", "error": "Trade not found."}, 404)


@post(path="/trades/waiting/stop/{campaign_id:str}")
async def waiting_campaign_stop(campaign_id: str) -> Any:
    """Stop a waiting sidestep campaign manually."""
    sidestep_campaigns = await SpotSidestepCampaignService.instance()
    stopped = await sidestep_campaigns.stop_campaign(campaign_id)
    if stopped:
        return {"result": "stopped"}
    return json_response({"result": "", "error": "Campaign not found."}, 404)


route_handlers = [
    open_trades,
    closed_trades,
    unsellable_trades,
    waiting_campaigns,
    closed_trades_length,
    closed_trades_pagination,
    trade_executions,
    closed_trade_delete,
    unsellable_trade_delete,
    waiting_campaign_stop,
]
