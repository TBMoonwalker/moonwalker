from quart import Quart, request, websocket
import argparse
import asyncio
import importlib
import os
from config import Config
from database import Database
from dca import Dca
from exchange import Exchange
from logger import LoggerFactory
from statistic import Statistic
from watcher import Watcher
from trading import Trading
from quart_cors import route_cors


######################################################
#                       Config                       #
######################################################

# load configuration file
attributes = Config()

# Parse and interpret options
parser = argparse.ArgumentParser(
    description="Moonwalker brings Signals directly to your exchange."
)

# Set logging facility
if attributes.get("debug", False):
    loglevel = "DEBUG"
else:
    loglevel = "INFO"

# Create db and logs directories if they don't exist already
try:
    os.makedirs("logs", exist_ok=True)
    os.makedirs("db", exist_ok=True)
except:
    print(
        "Error creating 'db' and 'logs' directory - please create them manually and report it as a bug!"
    )
    exit(1)

logging = LoggerFactory.get_logger("logs/moonwalker.log", "main", log_level=loglevel)

######################################################
#                        Init                        #
######################################################

# Import configured plugin
plugin = importlib.import_module(f"plugins.{attributes.get('plugin')}")
dca_strategy_plugin = None

# Import configured strategies
if attributes.get("dca_strategy", None):
    dca_strategy = importlib.import_module(
        f"strategies.{attributes.get('dca_strategy')}"
    )
    dca_strategy_plugin = dca_strategy.Strategy(
        ws_url=attributes.get("ws_url", None),
        loglevel=loglevel,
        btc_pulse=attributes.get("btc_pulse", False),
        currency=attributes.get("currency"),
    )
if attributes.get("init_buy_strategy", None):
    init_buy_strategy = importlib.import_module(
        f"strategies.{attributes.get('init_buy_strategy')}"
    )

# Initialize database
database = Database("trades.sqlite", loglevel)

# Initialize queues
order_queue = asyncio.Queue()
dca_queue = asyncio.Queue()
tickers_queue = asyncio.Queue()
stats_queue = asyncio.Queue()

# Initialize Signal plugin
signal_plugin = plugin.SignalPlugin(
    order_queue,
    ordersize=attributes.get("bo"),
    max_bots=attributes.get("max_bots"),
    ws_url=attributes.get("ws_url", None),
    loglevel=loglevel,
    plugin_settings=attributes.get("plugin_settings"),
    filter_values=attributes.get("filter", None),
    exchange=attributes.get("exchange"),
    currency=attributes.get("currency"),
    market=attributes.get("market", "spot"),
    pair_denylist=attributes.get("pair_denylist", None),
    pair_allowlist=attributes.get("pair_allowlist", None),
    topcoin_limit=attributes.get("topcoin_limit", None),
    volume=attributes.get("volume", None),
    dynamic_dca=attributes.get("dynamic_dca", False),
    btc_pulse=attributes.get("btc_pulse", False),
)

# Initialize Exchange module
exchange = Exchange(
    order=order_queue,
    tickers=tickers_queue,
    statistic=stats_queue,
    exchange=attributes.get("exchange"),
    key=attributes.get("key"),
    secret=attributes.get("secret"),
    password=attributes.get("password", None),
    currency=attributes.get("currency"),
    sandbox=attributes.get("sandbox", False),
    market=attributes.get("market", "spot"),
    dry_run=attributes.get("dry_run", True),
    loglevel=loglevel,
    fee_deduction=attributes.get("fee_deduction", False),
    order_check_range=attributes.get("order_check_range", 5),
)

# Initialize Watcher module
watcher = Watcher(
    dca=dca_queue,
    tickers=tickers_queue,
    dynamic_dca=attributes.get("dynamic_dca", False),
    exchange=attributes.get("exchange"),
    key=attributes.get("key"),
    secret=attributes.get("secret"),
    currency=attributes.get("currency"),
    sandbox=attributes.get("sandbox", False),
    market=attributes.get("market", "spot"),
    loglevel=loglevel,
    timeframe=attributes.get("timeframe", "1m"),
)

# Initialize DCA module
dca = Dca(
    dca=dca_queue,
    statistic=stats_queue,
    trailing_tp=attributes.get("trailing_tp", 0),
    dynamic_dca=attributes.get("dynamic_dca", False),
    dynamic_tp=attributes.get("dynamic_tp", 0),
    strategy=dca_strategy_plugin,
    order=order_queue,
    volume_scale=attributes.get("os"),
    step_scale=attributes.get("ss"),
    max_safety_orders=attributes.get("mstc", None),
    so=attributes.get("so", None),
    price_deviation=attributes.get("sos", None),
    tp=attributes.get("tp"),
    sl=attributes.get("sl", 10000),
    ws_url=attributes.get("ws_url", None),
    loglevel=loglevel,
    market=attributes.get("market", "spot"),
)

# Initialize Statistics module
statistic = Statistic(
    stats=stats_queue,
    loglevel=loglevel,
    market=attributes.get("market", "spot"),
    ws_url=attributes.get("ws_url", None),
    dynamic_dca=attributes.get("dynamic_dca", False),
)

# Initialize Trading module
trading = Trading(
    statistic=stats_queue,
    loglevel=loglevel,
    currency=attributes.get("currency"),
    order=order_queue,
)

# Initialize app
app = Quart(__name__)


######################################################
#                     Main methods                   #
######################################################


@app.websocket("/open_orders")
async def open_orders():
    try:
        while True:
            output = await statistic.open_orders()
            await websocket.send(output)
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Handle disconnection here
        logging.info("Client disconnected")
        raise


@app.websocket("/closed_orders")
async def closed_orders():
    try:
        while True:
            output = await statistic.closed_orders()
            await websocket.send(output)
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Handle disconnection here
        logging.info("Client disconnected")
        raise


@app.websocket("/statistics")
async def profit():
    try:
        while True:
            output = await statistic.profit_statistics()
            await websocket.send(output)
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Handle disconnection here
        logging.info("Client disconnected")
        raise


@app.route("/orders/sell/<symbol>", methods=["GET"])
@route_cors(allow_origin="*")
async def sell_order(symbol):
    response = await trading.manual_sell(symbol)
    if not response:
        response = {"result": ""}

    return response


@app.route("/orders/buy/<symbol>/<ordersize>", methods=["GET"])
@route_cors(allow_origin="*")
async def buy_order(symbol, ordersize):
    response = await trading.manual_buy(symbol, ordersize)
    if not response:
        response = {"result": ""}

    return response


@app.route("/orders/stop/<symbol>", methods=["GET"])
@route_cors(allow_origin="*")
async def stop_order(symbol):
    response = await trading.manual_stop(symbol)
    if not response:
        response = {"result": ""}

    return response


@app.route("/orders/closed/length")
@route_cors(allow_origin="*")
async def closed_orders_length():
    response = await statistic.closed_orders_length()
    if not response:
        response = {"result": ""}

    return response


@app.route("/orders/closed/<page>")
@route_cors(allow_origin="*")
async def closed_orders_pagination(page):
    response = await statistic.closed_orders(int(page))
    if not response:
        response = {"result": ""}

    return response


@app.route("/profit/statistics/<timestamp>")
@route_cors(allow_origin="*")
async def profit_statistics(timestamp=None):
    response = await statistic.profits_overall(timestamp)
    if not response:
        response = {"result": ""}

    return response


@app.before_serving
async def startup():
    await database.init()
    app.add_background_task(exchange.run)
    app.add_background_task(statistic.run)
    app.add_background_task(signal_plugin.run)

    if attributes.get("dca", None):
        app.add_background_task(watcher.watch_tickers)
        if not attributes.get("dry_run", True):
            app.add_background_task(watcher.watch_orders)
        app.add_background_task(watcher.update_symbols)
        app.add_background_task(dca.run)


@app.after_serving
async def shutdown():
    await signal_plugin.shutdown()

    if attributes.get("dca", None):
        await dca.shutdown()
        await watcher.shutdown()

    await statistic.shutdown()
    await exchange.shutdown()
    await database.shutdown()


######################################################
#                     Main                           #
######################################################

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=attributes.get("port", "8130"))
