import asyncio
import helper
import json
from service.statistic import Statistic
from controller import controller
from quart import websocket
from quart_cors import route_cors

logging = helper.LoggerFactory.get_logger(
    "logs/controller.log", "controller_statistics"
)

statistic = Statistic()


@controller.websocket("/statistic/profit")
async def profit():
    try:
        while True:
            output = json.dumps(await statistic.get_profit())
            await websocket.send(output)
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Handle disconnection here
        logging.info("Client disconnected")
        raise


@controller.route("/statistic/profit/<timestamp>/<period>")
@route_cors(
    allow_methods=["GET"],
    allow_origin=["*"],
)
async def profit_statistics(timestamp, period):
    response = json.dumps(await statistic.get_profits_overall(timestamp, period))
    if not response:
        response = {"result": ""}

    return response
