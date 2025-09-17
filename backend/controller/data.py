import helper
from service.data import Data
from controller import controller
from quart_cors import route_cors

data = Data()

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_data")


@controller.route(
    "/data/ohlcv/<symbol>/<timerange>/<timestamp_start>/<offset>",
    methods=["GET"],
)
@route_cors(allow_origin="*")
async def get_ohlcv_data(symbol, timerange, timestamp_start, offset):
    response = await data.get_ohlcv_for_pair(symbol, timerange, timestamp_start, offset)

    return response
