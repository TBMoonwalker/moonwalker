"""Signal plugin loader and runner."""

import asyncio
import importlib
import inspect
from typing import Any, Protocol, cast

import helper
from service.config import Config
from service.config_views import SignalPluginConfigView

logging = helper.LoggerFactory.get_logger("logs/signal.log", "signal")


class SignalPluginProtocol(Protocol):
    """Contract implemented by runtime signal plugins."""

    async def run(self, config: dict[str, Any]) -> None:
        """Run the plugin loop with the current config snapshot."""

    async def shutdown(self) -> None:
        """Stop the plugin loop and release resources."""


class SignalPluginLoadError(RuntimeError):
    """Raised when a configured signal plugin cannot be loaded safely."""


class SignalPluginLifecycleError(RuntimeError):
    """Raised when a loaded signal plugin violates the runtime contract."""


class Signal:
    """Manage signal plugin lifecycle and reload on config changes."""

    def __init__(self, watcher_queue: asyncio.Queue[Any]):
        self.watcher_queue = watcher_queue
        self.signal_name: str | None = None
        self.signal_plugin: SignalPluginProtocol | None = None
        self._task: asyncio.Task[Any] | None = None
        self._reload_lock = asyncio.Lock()
        self._reload_task: asyncio.Task[Any] | None = None
        self._pending_reload_config: dict[str, Any] | None = None

    async def init(self) -> None:
        """Initialize signal plugin based on current configuration."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config.snapshot())

    async def shutdown(self) -> None:
        """Cancel active plugin run task and call plugin shutdown hook."""
        self._pending_reload_config = None
        if self._reload_task is not None and not self._reload_task.done():
            self._reload_task.cancel()
            await asyncio.gather(self._reload_task, return_exceptions=True)
            self._reload_task = None

        await self._stop_current_plugin()

    def _load_plugin_instance(self, signal_name: str) -> SignalPluginProtocol:
        """Import and instantiate the configured signal plugin."""
        try:
            signal_module = importlib.import_module(f"signals.{signal_name}")
        except (ImportError, RuntimeError, TypeError, ValueError) as exc:
            raise SignalPluginLoadError(
                f"Failed to import signal plugin '{signal_name}': {exc}"
            ) from exc

        plugin_factory = getattr(signal_module, "SignalPlugin", None)
        if not callable(plugin_factory):
            raise SignalPluginLoadError(
                f"Signal plugin '{signal_name}' does not expose a callable SignalPlugin."
            )

        try:
            plugin = plugin_factory(self.watcher_queue)
        except (RuntimeError, TypeError, ValueError, OSError) as exc:
            raise SignalPluginLoadError(
                f"Failed to initialize signal plugin '{signal_name}': {exc}"
            ) from exc

        if not callable(getattr(plugin, "run", None)):
            raise SignalPluginLoadError(
                f"Signal plugin '{signal_name}' does not provide a callable run()."
            )
        if not callable(getattr(plugin, "shutdown", None)):
            raise SignalPluginLoadError(
                f"Signal plugin '{signal_name}' does not provide a callable shutdown()."
            )

        return cast(SignalPluginProtocol, plugin)

    def _start_plugin_task(
        self,
        signal_name: str,
        plugin: SignalPluginProtocol,
        config: dict[str, Any],
    ) -> asyncio.Task[Any]:
        """Start the plugin run loop and validate its coroutine contract."""
        try:
            run_result = plugin.run(config)
        except (RuntimeError, TypeError, ValueError, OSError) as exc:
            raise SignalPluginLoadError(
                f"Signal plugin '{signal_name}' failed before starting: {exc}"
            ) from exc

        if not inspect.iscoroutine(run_result):
            raise SignalPluginLoadError(
                f"Signal plugin '{signal_name}' run() must return a coroutine."
            )

        return asyncio.create_task(run_result)

    async def _shutdown_plugin(self, plugin: SignalPluginProtocol) -> None:
        """Run the plugin shutdown hook and enforce its awaitable contract."""
        try:
            shutdown_result = plugin.shutdown()
            if not inspect.isawaitable(shutdown_result):
                raise SignalPluginLifecycleError(
                    "Signal plugin shutdown() must return an awaitable."
                )
            await shutdown_result
        except asyncio.CancelledError:
            raise
        except (
            SignalPluginLifecycleError,
            RuntimeError,
            TypeError,
            ValueError,
            OSError,
        ) as exc:
            logging.warning("Signal plugin shutdown failed: %s", exc)

    async def _stop_current_plugin(self) -> None:
        """Shutdown and cancel the active signal plugin safely."""
        plugin = self.signal_plugin
        task = self._task

        self.signal_plugin = None
        self._task = None
        self.signal_name = None

        if plugin is not None:
            await self._shutdown_plugin(plugin)

        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _reload_plugin(self, config: dict[str, Any]) -> None:
        """Reload signal plugin in a serialized critical section."""
        async with self._reload_lock:
            await self._stop_current_plugin()

            signal_config = SignalPluginConfigView.from_config(config)
            signal_name = signal_config.signal_name
            if not signal_name:
                logging.error(
                    "No plugin configured. Please configure the plugin in the GUI"
                )
                return

            try:
                plugin = self._load_plugin_instance(signal_name)
                task = self._start_plugin_task(signal_name, plugin, config)
            except SignalPluginLoadError as exc:
                logging.error(
                    "Failed to load signal plugin '%s': %s",
                    signal_name,
                    exc,
                    exc_info=True,
                )
                self.signal_plugin = None
                self._task = None
                self.signal_name = None
                return

            self.signal_plugin = plugin
            self._task = task
            self.signal_name = signal_name

    async def _drain_plugin_reloads(self) -> None:
        """Serialize plugin reloads and coalesce rapid config bursts."""
        while self._pending_reload_config is not None:
            config = self._pending_reload_config
            self._pending_reload_config = None

            await self._reload_plugin(config)

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Reload the signal plugin if configuration changes."""
        logging.info("Reload signal plugin system")
        signal_config = SignalPluginConfigView.from_config(config)
        if signal_config.signal_name is not None:
            self._pending_reload_config = dict(config)
            if self._reload_task is None or self._reload_task.done():
                self._reload_task = asyncio.create_task(self._drain_plugin_reloads())
        else:
            logging.error(
                "No plugin configured. Please configure the plugin in the GUI"
            )
