import asyncio
import helper
from service.trades import Trades
from controller import controller
from quart import websocket
from quart_cors import route_cors

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_trades")
trades = Trades()


@controller.websocket("/trades/open")
async def open_trades():
    try:
        while True:
            output = await trades.get_open_trades()
            await websocket.send(output)
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Handle disconnection here
        logging.info("Client disconnected")
        raise


@controller.websocket("/trades/closed")
async def closed_trades():
    try:
        while True:
            output = await trades.get_closed_trades()
            await websocket.send(output)
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Handle disconnection here
        logging.info("Client disconnected")
        raise


@controller.route("/trades/closed/length")
@route_cors(
    allow_methods=["GET"],
    allow_origin=["*"],
)
async def closed_trades_length():
    response = await trades.get_closed_trades_length()
    if not response:
        response = {"result": ""}

    return response


@controller.route("/trades/closed/<page>")
@route_cors(
    allow_methods=["GET"],
    allow_origin=["*"],
)
async def closed_trades_pagination(page):
    response = await trades.get_closed_trades(int(page))
    if not response:
        response = {"result": ""}

    return response
