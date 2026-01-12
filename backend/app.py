from quart import Quart
import asyncio
import importlib
from controller import controller
from service.database import Database
from service.watcher import Watcher
from service.housekeeper import Housekeeper
from service.redis import redis_client, start_redis
from service.config import Config
from service.signal import Signal

# Initialize app
app = Quart(__name__)
app.register_blueprint(controller)


@app.before_serving
async def startup():
    app.redis_proc = start_redis()

    # Initialize queues
    watcher_queue = asyncio.Queue()

    # Initialize database
    database = Database()
    await database.init()

    # Initialize ConfigService (starts Redis listener)
    app.conf = await Config.instance()

    # Initialize watcher module
    watcher = Watcher()
    await watcher.init()

    # Initialize housekeeper module
    housekeeper = Housekeeper()
    await housekeeper.init()

    # Initialize signal module
    signal_plugin = Signal(watcher_queue, app)
    await signal_plugin.init()

    app.add_background_task(watcher.watch_incoming_symbols, watcher_queue)
    app.add_background_task(housekeeper.cleanup_ticker_database)
    app.add_background_task(watcher.watch_tickers)


@app.after_serving
async def shutdown():
    await app.signal_plugin.shutdown()
    await app.watcher.shutdown()
    await app.housekeeper.shutdown()
    await app.database.shutdown()
    await redis_client.aclose()

    if hasattr(app, "redis_proc"):
        app.redis_proc.terminate()


######################################################
#                     Main                           #
######################################################

if __name__ == "__main__":
    app.run(host="0.0.0.0", port="8130")
