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
