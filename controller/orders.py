import helper
from service.orders import Orders
from controller import controller
from quart_cors import route_cors

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_orders")
orders = Orders()


@controller.route("/orders/sell/<symbol>", methods=["GET"])
@route_cors(
    allow_methods=["GET"],
    allow_origin=["*"],
)
async def sell_order(symbol):
    if await orders.receive_sell_signal(symbol):
        return {"result": "sell"}
    else:
        return {"result": ""}


@controller.route("/orders/buy/<symbol>/<ordersize>", methods=["GET"])
@route_cors(
    allow_methods=["GET"],
    allow_origin=["*"],
)
async def buy_order(symbol, ordersize):
    if await orders.receive_buy_signal(symbol, ordersize):
        return {"result": "new_so"}
    else:
        return {"result": ""}


@controller.route("/orders/stop/<symbol>", methods=["GET"])
@route_cors(
    allow_methods=["GET"],
    allow_origin=["*"],
)
async def stop_order(symbol):
    if await orders.receive_stop_signal(symbol):
        return {"result": "stop"}
    else:
        return {"result": ""}
