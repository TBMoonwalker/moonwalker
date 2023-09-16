from quart import Quart, request
import argparse
import asyncio
import importlib
from config import Config
from database import Database
from dca import Dca
from exchange import Exchange
from watcher import Watcher
from logger import Logger


######################################################
#                       Config                       #
######################################################

# load configuration file
attributes = Config()

# Parse and interpret options
parser = argparse.ArgumentParser(
    description="TVBot bringing Signals directly to your exchange."
)

logging = Logger("main")

######################################################
#                        Init                        #
######################################################

# Import configured plugin
plugin = importlib.import_module(f"plugins.{attributes.get('plugin')}")

# Initialize database
database = Database("trades.sqlite")

# Initialize queues
order_queue = asyncio.Queue()
dca_queue = asyncio.Queue()
tickers_queue = asyncio.Queue()

# Initialize Signal plugin
signal_plugin = plugin.SignalPlugin(
    order_queue,
    token=attributes.get("token"),
    ordersize=attributes.get("bo"),
    max_bots=attributes.get("max_bots"),
)

# Initialize Exchange module
exchange = Exchange(
    order=order_queue,
    tickers=tickers_queue,
    exchange=attributes.get("exchange"),
    key=attributes.get("key"),
    secret=attributes.get("secret"),
    currency=attributes.get("currency"),
    sandbox=attributes.get("sandbox"),
    market=attributes.get("market"),
    leverage=attributes.get("leverage", 1),
)

watcher = Watcher(
    dca=dca_queue,
    tickers=tickers_queue,
    exchange=attributes.get("exchange"),
    key=attributes.get("key"),
    secret=attributes.get("secret"),
    currency=attributes.get("currency"),
    sandbox=attributes.get("sandbox"),
    market=attributes.get("market"),
)

# Initialize DCA module
dca = Dca(
    dca=dca_queue,
    dynamic_tp=attributes.get("dynamic_tp", False),
    dynamic_dca=attributes.get("dynamic_dca", False),
    order=order_queue,
    volume_scale=attributes.get("os"),
    step_scale=attributes.get("ss"),
    max_safety_orders=attributes.get("mstc"),
    so=attributes.get("so"),
    price_deviation=attributes.get("sos"),
    tp=attributes.get("tp"),
    max=attributes.get("max", 0),
    ws_url=attributes.get("ws_url", None),
)


# Initialize app
app = Quart(__name__)


######################################################
#                     Main methods                   #
######################################################


@app.route("/tv", methods=["POST"])
async def webhook():
    body = await request.get_data()
    await signal_plugin.get(body)

    return "ok"


@app.before_serving
async def startup():
    await database.init()
    app.add_background_task(exchange.run)
    if attributes.get("dca"):
        app.add_background_task(watcher.watch_tickers)
        app.add_background_task(watcher.watch_orders)
        app.add_background_task(watcher.update_symbols)
        app.add_background_task(dca.run)


@app.after_serving
async def shutdown():
    await database.shutdown()
    app.background_tasks.pop().cancel(exchange.run)
    if attributes.get("dca"):
        app.background_tasks.pop().cancel(dca.run)
        app.background_tasks.pop().cancel(watcher.update_symbols)
        app.background_tasks.pop().cancel(watcher.watch_orders)
        app.background_tasks.pop().cancel(watcher.watch_tickers)
        await watcher.shutdown()


######################################################
#                     Main                           #
######################################################

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=attributes.get("port", "8130"))
