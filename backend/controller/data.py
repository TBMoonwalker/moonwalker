from typing import Any

import helper
from quart_cors import route_cors

from controller import controller
from service.data import Data

data = Data()

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_data")


@controller.route(
    "/data/ohlcv/<symbol>/<timerange>/<timestamp_start>/<offset>",
    methods=["GET"],
)
@route_cors(allow_origin="*")
async def get_ohlcv_data(symbol: str, timerange: str, timestamp_start: str, offset: str) -> Any:
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
