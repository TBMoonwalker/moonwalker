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
        self._reload_lock = asyncio.Lock()
        self._reload_task: asyncio.Task[Any] | None = None
        self._pending_reload_config: dict[str, Any] | None = None

    async def init(self) -> None:
        """Initialize signal plugin based on current configuration."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config._cache)

    async def shutdown(self) -> None:
        """Cancel active plugin run task and call plugin shutdown hook."""
        self._pending_reload_config = None
        if self._reload_task is not None and not self._reload_task.done():
            await asyncio.gather(self._reload_task, return_exceptions=True)
            self._reload_task = None

        await self._stop_current_plugin()

    async def _stop_current_plugin(self) -> None:
        """Shutdown and cancel the active signal plugin safely."""
        plugin = self.signal_plugin
        task = self._task

        self.signal_plugin = None
        self._task = None
        self.signal_name = None

        if plugin is not None:
            shutdown = getattr(plugin, "shutdown", None)
            if callable(shutdown):
                try:
                    result = shutdown()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as exc:  # noqa: BLE001 - Continue cleanup on failure.
                    logging.warning("Signal plugin shutdown failed: %s", exc)

        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _reload_plugin(self, config: dict[str, Any]) -> None:
        """Reload signal plugin in a serialized critical section."""
        async with self._reload_lock:
            await self._stop_current_plugin()

            self.signal_name = str(config.get("signal", "")).strip()
            if not self.signal_name:
                logging.error(
                    "No plugin configured. Please configure the plugin in the GUI"
                )
                return

            try:
                signal_plugin = importlib.import_module(f"signals.{self.signal_name}")
                self.signal_plugin = signal_plugin.SignalPlugin(self.watcher_queue)
                self._task = asyncio.create_task(self.signal_plugin.run(config))
            except Exception as exc:  # noqa: BLE001 - Keep config loop alive.
                logging.error(
                    "Failed to load signal plugin '%s': %s",
                    self.signal_name,
                    exc,
                    exc_info=True,
                )
                self.signal_plugin = None
                self._task = None

    async def _drain_plugin_reloads(self) -> None:
        """Serialize plugin reloads and coalesce rapid config bursts."""
        while self._pending_reload_config is not None:
            config = self._pending_reload_config
            self._pending_reload_config = None

            try:
                await self._reload_plugin(config)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - Keep config loop alive.
                logging.error("Failed to reload signal plugin: %s", exc, exc_info=True)

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Reload the signal plugin if configuration changes."""
        logging.info("Reload signal plugin system")
        if config.get("signal") is not None:
            self._pending_reload_config = dict(config)
            if self._reload_task is None or self._reload_task.done():
                self._reload_task = asyncio.create_task(self._drain_plugin_reloads())
        else:
            logging.error(
                "No plugin configured. Please configure the plugin in the GUI"
            )
