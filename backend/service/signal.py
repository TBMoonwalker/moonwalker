"""Signal plugin loader and runner."""

import asyncio
import importlib
from typing import Any

import helper
from service.config import Config

logging = helper.LoggerFactory.get_logger("logs/signal.log", "signal")


class Signal:
    """Manage signal plugin lifecycle and reload on config changes."""

    def __init__(self, watcher_queue: asyncio.Queue[Any]):
        self.watcher_queue = watcher_queue
        self.signal_name: str | None = None
        self.signal_plugin: Any = None
        self._task: asyncio.Task[Any] | None = None

    async def init(self) -> None:
        """Initialize signal plugin based on current configuration."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config._cache)

    async def shutdown(self) -> None:
        """Cancel active plugin run task and call plugin shutdown hook."""
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

        if self.signal_plugin is not None:
            shutdown = getattr(self.signal_plugin, "shutdown", None)
            if callable(shutdown):
                result = shutdown()
                if asyncio.iscoroutine(result):
                    await result

    def _reload_plugin(self, config: dict[str, Any]) -> None:
        if self._task is not None:
            self._task.cancel()

        self.signal_name = str(config.get("signal", "")).strip()
        if not self.signal_name:
            logging.error(
                "No plugin configured. Please configure the plugin in the GUI"
            )
            return

        signal_plugin = importlib.import_module(f"signals.{self.signal_name}")
        self.signal_plugin = signal_plugin.SignalPlugin(self.watcher_queue)
        self._task = asyncio.create_task(self.signal_plugin.run(config))

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Reload the signal plugin if configuration changes."""
        logging.info("Reload signal plugin system")
        if config.get("signal") is not None:
            self._reload_plugin(config)
        else:
            logging.error(
                "No plugin configured. Please configure the plugin in the GUI"
            )
