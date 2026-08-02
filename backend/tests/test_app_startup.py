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


class _FakePlacementSummary:
    ready = True
    action_required: tuple[str, ...] = ()


class _FakePlacementOrders:
    async def reconcile_placement_intents(
        self,
        _config: dict[str, object],
    ) -> _FakePlacementSummary:
        return _FakePlacementSummary()

    async def close(self) -> None:
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


class _FakeDelistingProtectionFactory:
    @staticmethod
    async def instance() -> _FakeAutopilotMemoryService:
        return _FakeAutopilotMemoryService()


class _FailIfUsedSidestepCampaignFactory:
    @staticmethod
    async def instance():
        raise AssertionError(
            "startup should not initialize sidestep campaign boot hooks"
        )


class _FakeStartupLogger:
    def __init__(self) -> None:
        self.info_calls: list[tuple[str, tuple[object, ...]]] = []
        self.exception_calls: list[tuple[str, tuple[object, ...]]] = []

    def info(self, message: str, *args: object) -> None:
        self.info_calls.append((message, args))

    def exception(self, message: str, *args: object) -> None:
        self.exception_calls.append((message, args))


class _FakeRedisClient:
    async def aclose(self) -> None:
        return None


class _FakeMarketCapRankService:
    def __init__(self) -> None:
        self.start_calls = 0
        self.shutdown_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


async def _noop_async(*_args, **_kwargs) -> None:
    return None


@pytest.mark.asyncio
async def test_startup_step_logs_readiness_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeStartupLogger()
    monkeypatch.setattr(app_module, "logging", fake_logger)

    async def operation() -> str:
        return "ready"

    result = await app_module._run_startup_step("test step", operation)

    assert result == "ready"
    assert fake_logger.info_calls[0][0] == "Startup step started: %s"
    assert fake_logger.info_calls[0][1] == ("test step",)
    assert fake_logger.info_calls[1][0] == "Startup step finished: %s in %.3fs"
    assert fake_logger.info_calls[1][1][0] == "test step"
    assert isinstance(fake_logger.info_calls[1][1][1], float)


@pytest.mark.asyncio
async def test_lifespan_supervises_named_critical_and_optional_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_database = _FakeDatabase()
    fake_market_cap_service = _FakeMarketCapRankService()
    monkeypatch.setattr(app_module, "runtime_state", app_module.RuntimeState())
    monkeypatch.setattr(app_module, "start_redis", lambda: object())
    monkeypatch.setattr(app_module, "stop_redis", lambda _proc: None)
    monkeypatch.setattr(app_module, "redis_client", _FakeRedisClient())
    monkeypatch.setattr(
        app_module,
        "coin_market_cap_rank_service",
        fake_market_cap_service,
    )
    monkeypatch.setattr(app_module, "Database", lambda: fake_database)
    monkeypatch.setattr(app_module, "Orders", _FakePlacementOrders)
    monkeypatch.setattr(app_module, "Config", _FakeConfigFactory)
    monkeypatch.setattr(app_module, "Watcher", _FakeWatcher)
    monkeypatch.setattr(app_module, "Housekeeper", _FakeHousekeeper)
    monkeypatch.setattr(app_module, "GreenPhaseService", _FakeGreenPhaseFactory)
    monkeypatch.setattr(
        app_module,
        "AutopilotMemoryService",
        _FakeAutopilotMemoryFactory,
    )
    monkeypatch.setattr(
        app_module,
        "DelistingProtectionService",
        _FakeDelistingProtectionFactory,
    )
    monkeypatch.setattr(
        app_module,
        "SpotSidestepCampaignService",
        _FailIfUsedSidestepCampaignFactory,
        raising=False,
    )
    monkeypatch.setattr(app_module, "Signal", _FakeSignal)
    monkeypatch.setattr(
        app_module,
        "recover_pending_outcome_attributions",
        _noop_async,
    )
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

    async with app_module.runtime_lifespan(None):
        await asyncio.sleep(0)

        assert len(app_module.runtime_state.background_tasks) == 4
        assert {
            task.get_name() for task in app_module.runtime_state.background_tasks
        } == {
            "moonwalker:symbol-intake",
            "moonwalker:ticker-watcher",
            "moonwalker:housekeeping",
            "moonwalker:replay-candle-backfill",
        }
        assert fake_database.run_calls[:2] == [
            "instance",
            "reconcile_placement_intents",
        ]
        assert "backfill_trade_replay_candles_if_needed" in fake_database.run_calls
        assert not hasattr(app_module.runtime_state, "sidestep_campaign_service")
        assert fake_market_cap_service.start_calls == 1
        assert app_module.runtime_state.controller_services is not None
        assert (
            app_module.runtime_state.controller_services.orders
            is app_module.runtime_state.placement_orders
        )

    assert fake_market_cap_service.shutdown_calls == 1
    assert app_module.runtime_state.controller_services is None


@pytest.mark.asyncio
async def test_critical_runtime_task_fails_when_loop_exits() -> None:
    """A silently exited critical loop must fail the application lifespan."""

    async def exit_immediately() -> None:
        return None

    with pytest.raises(
        RuntimeError,
        match="Critical runtime task exited unexpectedly: ticker-watcher",
    ):
        await app_module._run_critical_runtime_task(
            "ticker-watcher",
            exit_immediately,
        )


@pytest.mark.asyncio
async def test_critical_runtime_task_preserves_swallowed_cancellation() -> None:
    """A loop that returns after cancellation must not look like a crash."""

    async def swallow_cancellation() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            return

    runner = asyncio.create_task(
        app_module._run_critical_runtime_task(
            "symbol-intake",
            swallow_cancellation,
        )
    )
    await asyncio.sleep(0)
    runner.cancel()

    with pytest.raises(asyncio.CancelledError):
        await runner


@pytest.mark.asyncio
async def test_optional_runtime_task_isolates_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay backfill failures should remain visible without stopping runtime."""
    fake_logger = _FakeStartupLogger()
    monkeypatch.setattr(app_module, "logging", fake_logger)

    async def fail() -> None:
        raise RuntimeError("corrupt replay row")

    await app_module._run_optional_runtime_task("replay-candle-backfill", fail)

    assert fake_logger.exception_calls == [
        ("Optional runtime task failed: %s", ("replay-candle-backfill",))
    ]


@pytest.mark.asyncio
async def test_lifespan_cleans_up_after_partial_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed startup must still enter the shared shutdown path."""
    calls: list[str] = []

    async def fail_startup() -> None:
        calls.append("startup")
        raise RuntimeError("database init failed")

    async def record_shutdown() -> None:
        calls.append("shutdown")

    monkeypatch.setattr(app_module, "startup", fail_startup)
    monkeypatch.setattr(app_module, "shutdown", record_shutdown)

    with pytest.raises(RuntimeError, match="database init failed"):
        async with app_module.runtime_lifespan(None):
            pass

    assert calls == ["startup", "shutdown"]


@pytest.mark.asyncio
async def test_lifespan_finishes_owned_work_before_dependency_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown must cancel owned work before closing its backing dependencies."""
    events: list[str] = []

    async def owned_loop(name: str) -> None:
        try:
            await asyncio.sleep(3600)
        finally:
            events.append(f"{name}:done")

    class OrderedDatabase:
        async def run_with_context(self, func, *args, **kwargs):
            return await func(*args, **kwargs)

        async def backfill_trade_replay_candles_if_needed(self) -> None:
            await owned_loop("replay")

        async def shutdown(self) -> None:
            events.append("database:shutdown")

    class OrderedWatcher:
        async def watch_incoming_symbols(self, _queue) -> None:
            await owned_loop("symbol-intake")

        async def watch_tickers(self) -> None:
            await owned_loop("ticker-watcher")

        async def shutdown(self) -> None:
            events.append("watcher:shutdown")

    class OrderedHousekeeper:
        async def cleanup_ticker_database(self) -> None:
            await owned_loop("housekeeping")

        async def shutdown(self) -> None:
            events.append("housekeeper:shutdown")

    class OrderedSignal:
        async def shutdown(self) -> None:
            events.append("signal:shutdown")

    class OrderedQueue:
        async def start(self, _task_group) -> None:
            events.append("queue:start")

        async def stop(self) -> None:
            events.append("queue:stop")

    class OrderedProvider:
        async def start(self) -> None:
            events.append("provider:start")

        async def close(self) -> None:
            events.append("provider:close")

    class OrderedRedis:
        async def aclose(self) -> None:
            events.append("redis:close")

    state = app_module.RuntimeState()

    async def ordered_startup() -> None:
        events.append("startup")
        state.redis_proc = object()
        state.watcher_queue = asyncio.Queue()
        state.database = OrderedDatabase()
        state.watcher = OrderedWatcher()
        state.housekeeper = OrderedHousekeeper()
        state.signal_plugin = OrderedSignal()

    async def recover_pending() -> None:
        events.append("recover")

    async def stop_trades_fanout() -> None:
        events.append("trades-fanout:stop")

    async def stop_statistics_fanout() -> None:
        events.append("statistics-fanout:stop")

    def stop_redis_process(_process) -> None:
        events.append("redis-process:stop")

    monkeypatch.setattr(app_module, "runtime_state", state)
    monkeypatch.setattr(app_module, "startup", ordered_startup)
    monkeypatch.setattr(app_module, "ai_work_queue", OrderedQueue())
    monkeypatch.setattr(app_module, "ai_provider_client", OrderedProvider())
    monkeypatch.setattr(app_module, "redis_client", OrderedRedis())
    monkeypatch.setattr(app_module, "stop_redis", stop_redis_process)
    monkeypatch.setattr(
        app_module,
        "recover_pending_outcome_attributions",
        recover_pending,
    )
    monkeypatch.setattr(
        app_module.trades_controller,
        "stop_websocket_fanout",
        stop_trades_fanout,
    )
    monkeypatch.setattr(
        app_module.statistics_controller,
        "stop_websocket_fanout",
        stop_statistics_fanout,
    )

    async with app_module.runtime_lifespan(None):
        events.append("running")
        await asyncio.sleep(0)

    assert events.index("queue:stop") < events.index("symbol-intake:done")
    for task_name in ("symbol-intake", "ticker-watcher", "housekeeping", "replay"):
        assert events.index(f"{task_name}:done") < events.index("trades-fanout:stop")
    ordered_shutdown_events = [
        "trades-fanout:stop",
        "statistics-fanout:stop",
        "signal:shutdown",
        "watcher:shutdown",
        "housekeeper:shutdown",
        "database:shutdown",
        "provider:close",
        "redis:close",
        "redis-process:stop",
    ]
    assert [event for event in events if event in ordered_shutdown_events] == (
        ordered_shutdown_events
    )


@pytest.mark.asyncio
async def test_runtime_cleanup_finishes_despite_repeated_cancellation() -> None:
    """Repeated lifespan cancellation must not interrupt resource cleanup."""
    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()
    cleanup_completed = asyncio.Event()

    async def cleanup() -> None:
        cleanup_started.set()
        await cleanup_release.wait()
        cleanup_completed.set()

    cleanup_runner = asyncio.create_task(
        app_module._finish_cleanup_despite_cancellation(cleanup())
    )
    await cleanup_started.wait()

    cleanup_runner.cancel()
    await asyncio.sleep(0)
    cleanup_runner.cancel()
    await asyncio.sleep(0)

    assert not cleanup_runner.done()
    assert not cleanup_completed.is_set()

    cleanup_release.set()
    await cleanup_runner

    assert cleanup_completed.is_set()
    assert not cleanup_runner.cancelled()


@pytest.mark.asyncio
async def test_shutdown_attempts_later_resources_after_early_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An early closer failure must not leak later runtime resources."""
    events: list[str] = []

    class FailingSignal:
        async def shutdown(self) -> None:
            events.append("signal")
            raise RuntimeError("signal close failed")

    class ShutdownService:
        def __init__(self, name: str) -> None:
            self.name = name

        async def shutdown(self) -> None:
            events.append(self.name)

    class CloseService:
        def __init__(self, name: str) -> None:
            self.name = name

        async def close(self) -> None:
            events.append(self.name)

    class RedisCloseService:
        async def aclose(self) -> None:
            events.append("redis")

    async def stop_trades() -> None:
        events.append("trades")

    async def stop_statistics() -> None:
        events.append("statistics")

    state = app_module.RuntimeState(
        signal_plugin=FailingSignal(),  # type: ignore[arg-type]
        watcher=ShutdownService("watcher"),  # type: ignore[arg-type]
        housekeeper=ShutdownService("housekeeper"),  # type: ignore[arg-type]
        placement_orders=CloseService("placement_orders"),  # type: ignore[arg-type]
        market_cap_rank_service=ShutdownService("market_cap"),  # type: ignore[arg-type]
        database=ShutdownService("database"),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(app_module, "runtime_state", state)
    monkeypatch.setattr(
        app_module.trades_controller,
        "stop_websocket_fanout",
        stop_trades,
    )
    monkeypatch.setattr(
        app_module.statistics_controller,
        "stop_websocket_fanout",
        stop_statistics,
    )
    monkeypatch.setattr(app_module, "ai_provider_client", CloseService("provider"))
    monkeypatch.setattr(app_module, "redis_client", RedisCloseService())

    with pytest.raises(
        app_module.RuntimeShutdownError,
        match="Moonwalker shutdown failed",
    ):
        await app_module.shutdown()

    assert events == [
        "trades",
        "statistics",
        "signal",
        "watcher",
        "housekeeper",
        "placement_orders",
        "market_cap",
        "database",
        "provider",
        "redis",
    ]
    assert state.signal_plugin is None
    assert state.placement_orders is None
    assert state.database is None
