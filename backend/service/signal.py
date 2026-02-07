"""Signal plugin loader and runner."""

import asyncio
import importlib
from typing import Any

import helper
from service.config import Config

logging = helper.LoggerFactory.get_logger("logs/signal.log", "signal")


class Signal:
    """Manage signal plugin lifecycle and reload on config changes."""

    def __init__(self, watcher_queue: asyncio.Queue, app: Any):
        self.watcher_queue = watcher_queue
        self.signal = None
        self.signal_plugin = None
        self.app = app

    async def init(self) -> None:
        """Initialize signal plugin based on current configuration."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config._cache)

    def __reload_plugin(self, config: dict[str, Any]) -> None:
        try:
            self.app.signal_background_task.cancel()
        except Exception:
            # Broad catch: background task may not exist yet.
            pass
        self.signal = config.get("signal")
        signal_plugin = importlib.import_module(f"signals.{self.signal}")
        self.signal_plugin = signal_plugin.SignalPlugin(self.watcher_queue)
        self.app.signal_background_task = asyncio.ensure_future(
            self.signal_plugin.run(config)
        )

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Reload the signal plugin if configuration changes."""
        logging.info("Reload signal plugin system")
        if config.get("signal") is not None:
            self.__reload_plugin(config)
        else:
            logging.error(
                "No plugin configured. Please configure the plugin in the GUI"
            )
