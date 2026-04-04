"""Data API endpoints."""

from typing import Any

import helper
from litestar.connection import Request
from litestar.exceptions import SerializationException
from litestar.handlers import get, post
from service.config import Config
from service.data import Data

data = Data()

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_data")


@get(path="/data/ohlcv/{symbol:str}/{timerange:str}/{timestamp_start:str}/{offset:str}")
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


@get(
    path="/data/ohlcv/"
    "{symbol:str}/{timerange:str}/{timestamp_start:str}/{timestamp_end:str}/{offset:str}"
)
async def get_ohlcv_data_until(
    symbol: str,
    timerange: str,
    timestamp_start: str,
    timestamp_end: str,
    offset: str,
) -> Any:
    """Get OHLCV data for a bounded start/end replay window."""
    response = await data.get_ohlcv_for_pair(
        symbol,
        timerange,
        timestamp_start,
        offset,
        timestamp_end=float(timestamp_end),
    )
    return response


@get(path="/data/exchange/symbols/{currency:str}")
async def get_exchange_symbols(currency: str) -> Any:
    """Get exchange symbols for a configured quote currency."""
    config = await Config.instance()
    symbols = await data.get_exchange_symbols_for_currency(config.snapshot(), currency)
    return {"symbols": symbols}


@post(path="/data/exchange/symbols")
async def get_exchange_symbols_from_draft(request: Request[Any, Any, Any]) -> Any:
    """Get exchange symbols using draft exchange settings from request payload."""
    try:
        payload = await request.json()
    except SerializationException:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    config = await Config.instance()
    exchange_config = config.snapshot()

    draft_exchange_config = payload.get("exchange_config")
    if isinstance(draft_exchange_config, dict):
        exchange_config.update(draft_exchange_config)

    currency = payload.get("currency") or exchange_config.get("currency")
    if not currency:
        return {"symbols": [], "missing": ["currency"]}

    required_fields = ("exchange", "key", "secret")
    missing = [field for field in required_fields if not exchange_config.get(field)]
    if missing:
        return {"symbols": [], "missing": missing}

    symbols = await data.get_exchange_symbols_for_currency(exchange_config, currency)
    return {"symbols": symbols, "missing": []}


route_handlers = [
    get_ohlcv_data,
    get_ohlcv_data_until,
    get_exchange_symbols,
    get_exchange_symbols_from_draft,
]
