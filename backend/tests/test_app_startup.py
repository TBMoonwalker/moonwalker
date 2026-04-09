import asyncio

import app as app_module
import pytest


class _FakeConfig:
    def snapshot(self) -> dict[str, object]:
        return {}


class _FakeDatabase:
    def __init__(self) -> None:
        self.run_calls: list[str] = []

    async def init(self) -> None:
        return None

    async def run_with_context(self, func, *args, **kwargs):
        self.run_calls.append(getattr(func, "__name__", "unknown"))
        return await func(*args, **kwargs)

    async def backfill_trade_replay_candles_if_needed(self) -> None:
        await asyncio.sleep(3600)

    async def shutdown(self) -> None:
        return None


class _FakeWatcher:
    async def init(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def watch_incoming_symbols(self, _queue) -> None:
        await asyncio.sleep(3600)

    async def watch_tickers(self) -> None:
        await asyncio.sleep(3600)


class _FakeHousekeeper:
    async def init(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def cleanup_ticker_database(self) -> None:
        await asyncio.sleep(3600)


class _FakeGreenPhaseService:
    async def start(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None


class _FakeSignal:
    def __init__(self, _queue) -> None:
        return None

    async def init(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None


class _FakeConfigFactory:
    @staticmethod
    async def instance() -> _FakeConfig:
        return _FakeConfig()


class _FakeGreenPhaseFactory:
    @staticmethod
    async def instance() -> _FakeGreenPhaseService:
        return _FakeGreenPhaseService()


class _FakeAutopilotMemoryService:
    async def start(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None


class _FakeAutopilotMemoryFactory:
    @staticmethod
    async def instance() -> _FakeAutopilotMemoryService:
        return _FakeAutopilotMemoryService()


async def _noop_async(*_args, **_kwargs) -> None:
    return None


@pytest.mark.asyncio
async def test_startup_schedules_replay_backfill_as_background_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_database = _FakeDatabase()
    monkeypatch.setattr(app_module, "runtime_state", app_module.RuntimeState())
    monkeypatch.setattr(app_module, "start_redis", lambda: object())
    monkeypatch.setattr(app_module, "stop_redis", lambda _proc: None)
    monkeypatch.setattr(app_module, "Database", lambda: fake_database)
    monkeypatch.setattr(app_module, "Config", _FakeConfigFactory)
    monkeypatch.setattr(app_module, "Watcher", _FakeWatcher)
    monkeypatch.setattr(app_module, "Housekeeper", _FakeHousekeeper)
    monkeypatch.setattr(app_module, "GreenPhaseService", _FakeGreenPhaseFactory)
    monkeypatch.setattr(
        app_module,
        "AutopilotMemoryService",
        _FakeAutopilotMemoryFactory,
    )
    monkeypatch.setattr(app_module, "Signal", _FakeSignal)
    monkeypatch.setattr(
        app_module.trades_controller,
        "start_websocket_fanout",
        _noop_async,
    )
    monkeypatch.setattr(
        app_module.statistics_controller,
        "start_websocket_fanout",
        _noop_async,
    )
    monkeypatch.setattr(
        app_module.trades_controller,
        "stop_websocket_fanout",
        _noop_async,
    )
    monkeypatch.setattr(
        app_module.statistics_controller,
        "stop_websocket_fanout",
        _noop_async,
    )

    await app_module.startup()
    await asyncio.sleep(0)

    assert len(app_module.runtime_state.background_tasks) == 4
    assert "backfill_trade_replay_candles_if_needed" in fake_database.run_calls

    await app_module.shutdown()
