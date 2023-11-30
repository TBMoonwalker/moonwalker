from quart import Quart, request, websocket
import argparse
import asyncio
import importlib
import random
import json
from config import Config
from database import Database
from dca import Dca
from exchange import Exchange
from logger import LoggerFactory
from statistic import Statistic
from watcher import Watcher
from quart_cors import route_cors


######################################################
#                       Config                       #
######################################################

# load configuration file
attributes = Config()

# Parse and interpret options
parser = argparse.ArgumentParser(
    description="TVBot bringing Signals directly to your exchange."
)

# Set logging facility
if attributes.get("debug", False):
    loglevel = "DEBUG"
else:
    loglevel = "INFO"

logging = LoggerFactory.get_logger("moonwalker.log", "main", log_level=loglevel)

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
        ws_url=attributes.get("ws_url", None), loglevel=loglevel
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
    plugin_settings=attributes.get("plugin_settings", None),
    filter_values=attributes.get("filter", None),
    exchange=attributes.get("exchange"),
    currency=attributes.get("currency"),
    market=attributes.get("market"),
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
    currency=attributes.get("currency"),
    sandbox=attributes.get("sandbox"),
    market=attributes.get("market"),
    leverage=attributes.get("leverage", 1),
    margin_type=attributes.get("margin_type", "isolated"),
    dry_run=attributes.get("dry_run"),
    loglevel=loglevel,
    fee_deduction=attributes.get("fee_deduction", False),
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
    sandbox=attributes.get("sandbox"),
    market=attributes.get("market"),
    loglevel=loglevel,
    timeframe=attributes.get("timeframe"),
)

# Initialize DCA module
dca = Dca(
    dca=dca_queue,
    statistic=stats_queue,
    trailing_tp=attributes.get("trailing_tp", 0),
    dynamic_dca=attributes.get("dynamic_dca", False),
    strategy=dca_strategy_plugin,
    order=order_queue,
    volume_scale=attributes.get("os", None),
    step_scale=attributes.get("ss", None),
    max_safety_orders=attributes.get("mstc", None),
    so=attributes.get("so", None),
    price_deviation=attributes.get("sos", None),
    tp=attributes.get("tp"),
    sl=attributes.get("sl", None),
    max_active=attributes.get("max", 0),
    ws_url=attributes.get("ws_url", None),
    loglevel=loglevel,
    market=attributes.get("market"),
)

# Initialize Statistics module
statistic = Statistic(
    stats=stats_queue, loglevel=loglevel, market=attributes.get("market")
)

# Initialize app
app = Quart(__name__)


######################################################
#                     Main methods                   #
######################################################


@app.route("/tv", methods=["POST"])
async def webhook():
    body = await request.get_data()
    # Internal plugins don't need a weblistener
    if attributes.get("plugin_type") == "external":
        await signal_plugin.get(body)

    return "ok"


@app.route("/safety_orders/<symbol>", methods=["GET"])
@route_cors(allow_origin="*")
async def trades(symbol):
    response = await statistic.safety_orders(symbol)
    if not response:
        response = {"result": ""}

    return response


@app.websocket("/open_orders/")
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


@app.before_serving
async def startup():
    await database.init()
    app.add_background_task(exchange.run)
    app.add_background_task(statistic.run)

    if attributes.get("plugin_type") == "internal":
        app.add_background_task(signal_plugin.run)

    if attributes.get("dca", None):
        app.add_background_task(watcher.watch_tickers)
        app.add_background_task(watcher.watch_orders)
        app.add_background_task(watcher.update_symbols)
        app.add_background_task(dca.run)


@app.after_serving
async def shutdown():
    if attributes.get("plugin_type") == "internal":
        try:
            app.background_tasks.pop().cancel(signal_plugin.run)
        except:
            logging.info(
                "Plugin seems not to be an internal one - please change your configuration to external."
            )

    if attributes.get("dca", None):
        app.background_tasks.pop().cancel(dca.run)
        app.background_tasks.pop().cancel(watcher.update_symbols)
        app.background_tasks.pop().cancel(watcher.watch_orders)
        app.background_tasks.pop().cancel(watcher.watch_tickers)
        await watcher.shutdown()
        await database.shutdown()

    app.background_tasks.pop().cancel(statistic.run)
    app.background_tasks.pop().cancel(exchange.run)


######################################################
#                     Main                           #
######################################################

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=attributes.get("port", "8130"))
