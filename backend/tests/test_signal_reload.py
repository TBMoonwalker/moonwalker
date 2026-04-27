import asyncio
import types

import pytest
import service.signal as signal_module
from service.signal import Signal


@pytest.mark.asyncio
async def test_signal_reload_coalesces_rapid_config_changes(monkeypatch) -> None:
    watcher_queue: asyncio.Queue[list[str]] = asyncio.Queue()
    signal = Signal(watcher_queue)
    events: list[str] = []
    old_shutdown_started = asyncio.Event()
    old_shutdown_release = asyncio.Event()
    created_plugins: list[object] = []

    class BlockingPlugin:
        async def shutdown(self) -> None:
            events.append("old_shutdown_start")
            old_shutdown_started.set()
            await old_shutdown_release.wait()
            events.append("old_shutdown_end")

    async def old_run() -> None:
        await asyncio.sleep(3600)

    signal.signal_plugin = BlockingPlugin()
    signal.signal_name = "old"
    signal._task = asyncio.create_task(old_run())

    def fake_import_module(module_name: str) -> types.SimpleNamespace:
        plugin_name = module_name.split(".")[-1]

        class FakePlugin:
            def __init__(self, _watcher_queue: asyncio.Queue[list[str]]) -> None:
                self.plugin_name = plugin_name
                self.shutdown_calls = 0
                created_plugins.append(self)

            async def run(self, _config: dict[str, object]) -> None:
                await asyncio.sleep(3600)

            async def shutdown(self) -> None:
                self.shutdown_calls += 1

        return types.SimpleNamespace(SignalPlugin=FakePlugin)

    monkeypatch.setattr(signal_module.importlib, "import_module", fake_import_module)

    signal.on_config_change({"signal": "asap"})
    await asyncio.wait_for(old_shutdown_started.wait(), timeout=1)

    first_reload_task = signal._reload_task
    signal.on_config_change({"signal": "csv_signal"})

    assert signal._reload_task is first_reload_task

    old_shutdown_release.set()
    await asyncio.wait_for(signal._reload_task, timeout=1)

    assert [plugin.plugin_name for plugin in created_plugins] == [
        "asap",
        "csv_signal",
    ]
    assert created_plugins[0].shutdown_calls == 1
    assert created_plugins[1].shutdown_calls == 0
    assert signal.signal_name == "csv_signal"
    assert signal.signal_plugin is created_plugins[1]

    await signal.shutdown()


@pytest.mark.asyncio
async def test_signal_reload_rejects_module_without_signal_plugin(monkeypatch) -> None:
    signal = Signal(asyncio.Queue())

    def fake_import_module(_module_name: str) -> types.SimpleNamespace:
        return types.SimpleNamespace()

    monkeypatch.setattr(signal_module.importlib, "import_module", fake_import_module)

    await signal._reload_plugin({"signal": "broken"})

    assert signal.signal_name is None
    assert signal.signal_plugin is None
    assert signal._task is None


@pytest.mark.asyncio
async def test_signal_reload_rejects_non_async_run(monkeypatch) -> None:
    signal = Signal(asyncio.Queue())

    def fake_import_module(_module_name: str) -> types.SimpleNamespace:
        class FakePlugin:
            def __init__(self, _watcher_queue: asyncio.Queue[list[str]]) -> None:
                return None

            def run(self, _config: dict[str, object]) -> None:
                return None

            async def shutdown(self) -> None:
                return None

        return types.SimpleNamespace(SignalPlugin=FakePlugin)

    monkeypatch.setattr(signal_module.importlib, "import_module", fake_import_module)

    await signal._reload_plugin({"signal": "broken"})

    assert signal.signal_name is None
    assert signal.signal_plugin is None
    assert signal._task is None


@pytest.mark.asyncio
async def test_signal_shutdown_cancels_inflight_reload() -> None:
    signal = Signal(asyncio.Queue())
    cancelled = asyncio.Event()

    async def blocked_reload() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    signal._reload_task = asyncio.create_task(blocked_reload())
    await asyncio.sleep(0)

    await signal.shutdown()

    assert cancelled.is_set()
    assert signal._reload_task is None


@pytest.mark.asyncio
async def test_signal_plugin_crash_is_logged_and_restarted(monkeypatch) -> None:
    signal = Signal(asyncio.Queue())
    signal.PLUGIN_RESTART_DELAY_SECONDS = 0
    created_plugins: list[object] = []
    error_logs: list[str] = []

    class FakePlugin:
        def __init__(self, _watcher_queue: asyncio.Queue[list[str]]) -> None:
            self.shutdown_calls = 0
            created_plugins.append(self)

        async def run(self, _config: dict[str, object]) -> None:
            if len(created_plugins) == 1:
                raise RuntimeError("websocket receive failed")
            await asyncio.sleep(3600)

        async def shutdown(self) -> None:
            self.shutdown_calls += 1

    def fake_import_module(_module_name: str) -> types.SimpleNamespace:
        return types.SimpleNamespace(SignalPlugin=FakePlugin)

    def capture_error(message: str, *args, **_kwargs) -> None:
        error_logs.append(message % args if args else message)

    async def wait_for_restart() -> None:
        while len(created_plugins) < 2:
            await asyncio.sleep(0)

    monkeypatch.setattr(signal_module.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(signal_module.logging, "error", capture_error)

    await signal._reload_plugin({"signal": "sym_signals"})
    await asyncio.wait_for(wait_for_restart(), timeout=1)

    assert any("websocket receive failed" in entry for entry in error_logs)
    assert created_plugins[0].shutdown_calls == 1
    assert signal.signal_plugin is created_plugins[1]
    assert signal.signal_name == "sym_signals"
    assert signal._task is not None
    assert not signal._task.done()

    await signal.shutdown()
