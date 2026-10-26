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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,enabled",
    [
        ("asap", False),
        ("csv_signal", False),
        ("sym_signals", True),
        ("websocket_signal", True),
    ],
)
async def test_accumulation_loader_rejects_unsupported_or_disabled_entry(
    monkeypatch, name, enabled
):
    signal = Signal(asyncio.Queue())
    if enabled:
        signal.accumulation_entry = object()

    def unexpected(_name):
        raise AssertionError("Unsupported accumulation setup must not start a plugin")

    monkeypatch.setattr(signal, "_load_plugin_instance", unexpected)
    await signal._reload_plugin({"signal": name, "trade_mode": "accumulation"})
    assert signal.signal_plugin is None
    assert signal._task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["asap", "csv_signal"])
async def test_demo_accumulation_loader_starts_supported_plugin(monkeypatch, name):
    signal = Signal(asyncio.Queue())
    signal.accumulation_entry = object()
    started = asyncio.Event()

    class DemoPlugin:
        def __init__(self, queue):
            self.accumulation_entry = None

        async def run(self, config):
            assert config["dry_run"] is True
            assert self.accumulation_entry is signal.accumulation_entry
            started.set()
            await asyncio.Event().wait()

        async def shutdown(self):
            pass

    monkeypatch.setattr(
        signal_module.importlib,
        "import_module",
        lambda _: types.SimpleNamespace(SignalPlugin=DemoPlugin),
    )
    try:
        await signal._reload_plugin(
            {
                "signal": name,
                "trade_mode": "accumulation",
                "dry_run": True,
            }
        )
        assert signal.signal_name == name
        await asyncio.wait_for(started.wait(), 1)
    finally:
        await signal.shutdown()


@pytest.mark.asyncio
async def test_identical_configuration_does_not_cancel_active_entry(monkeypatch):
    signal = Signal(asyncio.Queue())
    created = []

    class Plugin:
        def __init__(self, queue):
            self.shutdown_calls = 0
            created.append(self)

        async def run(self, config):
            await asyncio.Event().wait()

        async def shutdown(self):
            self.shutdown_calls += 1

    monkeypatch.setattr(
        signal_module.importlib,
        "import_module",
        lambda _: types.SimpleNamespace(SignalPlugin=Plugin),
    )
    config = {"signal": "asap", "dry_run": True}
    try:
        await signal._reload_plugin(config)
        original = signal._task
        await signal._reload_plugin(dict(config))
        assert signal._task is original and not original.cancelled()
        assert len(created) == 1 and created[0].shutdown_calls == 0
        await signal._reload_plugin({**config, "currency": "usdc"})
        assert len(created) == 2 and created[0].shutdown_calls == 1
    finally:
        await signal.shutdown()
