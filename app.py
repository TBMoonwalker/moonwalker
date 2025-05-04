from quart import Quart
import asyncio
import importlib
import os
import helper
from controller import controller
from service.database import Database
from service.watcher import Watcher
from service.housekeeper import Housekeeper


######################################################
#                       Config                       #
######################################################

# load configuration file
attributes = helper.Config()

logging = helper.LoggerFactory.get_logger("logs/moonwalker.log", "main")

######################################################
#                        Init                        #
######################################################

# Queues
watcher_queue = asyncio.Queue()

# Import configured plugin
plugin = importlib.import_module(f"plugins.{attributes.get('plugin')}")

# Initialize database
database = Database()

# Initialize Signal plugin
signal_plugin = plugin.SignalPlugin(watcher_queue)

# Initialize Watcher module
watcher = Watcher()

# Initialize Housekeeper module
housekeeper = Housekeeper()

# Initialize app
app = Quart(__name__)
app.register_blueprint(controller)


@app.before_serving
async def startup():
    await database.init()
    app.add_background_task(watcher.watch_incoming_symbols, watcher_queue)
    app.add_background_task(signal_plugin.run)

    if attributes.get("dca", None):
        app.add_background_task(housekeeper.cleanup_ticker_database)
        app.add_background_task(watcher.watch_tickers)


@app.after_serving
async def shutdown():
    await signal_plugin.shutdown()

    if attributes.get("dca", None):
        await watcher.shutdown()
        await housekeeper.shutdown()
    await database.shutdown()


######################################################
#                     Main                           #
######################################################

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=attributes.get("port", "8130"))
