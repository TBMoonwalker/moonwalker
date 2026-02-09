"""Quart application entry point."""

import asyncio
import os

from controller import controller
from quart import Quart
from service.config import Config
from service.database import Database
from service.housekeeper import Housekeeper
from service.redis import redis_client, start_redis
from service.signal import Signal
from service.watcher import Watcher

# Initialize app
app = Quart(__name__)
app.register_blueprint(controller)


@app.before_serving
async def startup() -> None:
    app.redis_proc = start_redis()

    # Initialize queues
    watcher_queue = asyncio.Queue()

    # Initialize database
    app.database = Database()
    await app.database.init()

    # Initialize ConfigService (starts Redis listener)
    app.conf = await Config.instance()

    # Initialize watcher module
    app.watcher = Watcher()
    await app.watcher.init()

    # Initialize housekeeper module
    app.housekeeper = Housekeeper()
    await app.housekeeper.init()

    # Initialize signal module
    app.signal_plugin = Signal(watcher_queue, app)
    await app.signal_plugin.init()

    app.add_background_task(app.watcher.watch_incoming_symbols, watcher_queue)
    app.add_background_task(app.housekeeper.cleanup_ticker_database)
    app.add_background_task(app.watcher.watch_tickers)


@app.after_serving
async def shutdown() -> None:
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
    port = os.getenv("MOONWALKER_PORT", "8130")
    app.run(host="0.0.0.0", port=port)
