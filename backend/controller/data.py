"""Data API endpoints."""

from typing import Any

import helper
from controller import controller
from quart import jsonify, request
from quart_cors import route_cors
from service.config import Config
from service.data import Data

data = Data()

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_data")


@controller.route(
    "/data/ohlcv/<symbol>/<timerange>/<timestamp_start>/<offset>",
    methods=["GET"],
)
@route_cors(allow_origin="*")
async def get_ohlcv_data(
    symbol: str, timerange: str, timestamp_start: str, offset: str
) -> Any:
    """Get OHLCV (Open, High, Low, Close, Volume) data for a trading pair.

    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT").
        timerange: Time range for the data (e.g., "1h", "1d").
        timestamp_start: Start timestamp for the query.
        offset: Offset for pagination.

    Returns:
        OHLCV data for the requested parameters.
    """
    response = await data.get_ohlcv_for_pair(symbol, timerange, timestamp_start, offset)

    return response


@controller.route("/data/exchange/symbols/<currency>", methods=["GET"])
@route_cors(allow_origin="*")
async def get_exchange_symbols(currency: str) -> Any:
    """Get exchange symbols for a configured quote currency."""
    config = await Config.instance()
    symbols = await data.get_exchange_symbols_for_currency(config._cache, currency)
    return jsonify({"symbols": symbols})


@controller.route("/data/exchange/symbols", methods=["POST"])
@route_cors(allow_origin="*")
async def get_exchange_symbols_from_draft() -> Any:
    """Get exchange symbols using draft exchange settings from request payload."""
    payload = await request.get_json(silent=True) or {}

    config = await Config.instance()
    exchange_config = dict(config._cache)

    draft_exchange_config = payload.get("exchange_config")
    if isinstance(draft_exchange_config, dict):
        exchange_config.update(draft_exchange_config)

    currency = payload.get("currency") or exchange_config.get("currency")
    if not currency:
        return jsonify({"symbols": [], "missing": ["currency"]})

    required_fields = ("exchange", "key", "secret")
    missing = [field for field in required_fields if not exchange_config.get(field)]
    if missing:
        return jsonify({"symbols": [], "missing": missing})

    symbols = await data.get_exchange_symbols_for_currency(exchange_config, currency)
    return jsonify({"symbols": symbols, "missing": []})
