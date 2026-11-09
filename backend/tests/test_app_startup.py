import asyncio
from unittest.mock import AsyncMock, Mock

import app as app_module
import pytest
from httpx import ASGITransport, AsyncClient
from litestar import Litestar
from litestar.handlers import get, post
from litestar.params import FromPath
from service.ai_work_queue import AiWorkQueue
from service.background_work_queue import BoundedWorkQueue


class _FullFakeLogger:
    def __init__(self) -> None:
        self.info_calls: list[tuple[str, tuple[object, ...]]] = []
        self.error_calls: list[tuple[str, tuple[object, ...]]] = []
        self.exception_calls: list[tuple[str, tuple[object, ...]]] = []

    def info(self, message: str, *args: object) -> None:
        self.info_calls.append((message, args))

    def error(self, message: str, *args: object) -> None:
        self.error_calls.append((message, args))

    def exception(self, message: str, *args: object) -> None:
        self.exception_calls.append((message, args))


class _FakeConfig:
    def snapshot(self) -> dict[str, object]:
        return {}

    async def _listen(self) -> None:
        await asyncio.sleep(3600)

    async def stop_listener(self) -> None:
        return None


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
    remaining: int = 0


class _FakePlacementRecovery:
    def __init__(self, *, lifecycle: object) -> None:
        self.dca = lifecycle

    async def reconcile_placement_intents(
        self,
        _config: dict[str, object],
    ) -> _FakePlacementSummary:
        return _FakePlacementSummary()

    def build_placement_repair(self) -> object:
        return object()

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
async def test_startup_logs_when_frontend_not_staged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing staged SPA must surface as an error log before any step runs."""
    fake_logger = _FullFakeLogger()
    monkeypatch.setattr(app_module, "logging", fake_logger)
    monkeypatch.setattr(
        app_module, "frontend_staging_warning", lambda: "Frontend not staged"
    )
    monkeypatch.setattr(app_module, "runtime_state", app_module.RuntimeState())

    def start_redis() -> object:
        raise RuntimeError("redis start blocked after staging log")

    monkeypatch.setattr(app_module, "start_redis", start_redis)

    with pytest.raises(RuntimeError, match="redis start blocked"):
        await app_module.startup()

    assert "Frontend not staged; the web dashboard will be unavailable: %s" in {
        message for message, _args in fake_logger.error_calls
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("with_accumulation", [False, True])
async def test_lifespan_supervises_named_critical_and_optional_tasks(
    monkeypatch: pytest.MonkeyPatch,
    with_accumulation: bool,
) -> None:
    fake_database = _FakeDatabase()
    fake_market_cap_service = _FakeMarketCapRankService()
    monkeypatch.setattr(app_module, "ai_work_queue", AiWorkQueue())
    monkeypatch.setattr(
        app_module,
        "replay_repair_queue",
        BoundedWorkQueue(
            name="replay-repair-test",
            task_prefix="replay-repair",
            logger=app_module.logging,
            capacity=128,
            worker_count=1,
        ),
    )
    accumulation = _FakeAccumulationRuntime() if with_accumulation else None
    monkeypatch.setattr(
        app_module, "build_accumulation_runtime", lambda _provider: accumulation
    )
    monkeypatch.setattr(app_module, "runtime_state", app_module.RuntimeState())
    monkeypatch.setattr(app_module, "start_redis", lambda: object())
    monkeypatch.setattr(app_module, "redis_client", _FakeRedisClient())
    monkeypatch.setattr(
        app_module,
        "coin_market_cap_rank_service",
        fake_market_cap_service,
    )
    monkeypatch.setattr(app_module, "Database", lambda: fake_database)
    monkeypatch.setattr(app_module, "PlacementRecoveryEntry", _FakePlacementRecovery)
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

        assert len(app_module.runtime_state.background_tasks) == (
            6 if with_accumulation else 5
        )
        assert {
            task.get_name() for task in app_module.runtime_state.background_tasks
        } == (
            {
                "moonwalker:symbol-intake",
                "moonwalker:ticker-watcher",
                "moonwalker:housekeeping",
                "moonwalker:replay-candle-backfill",
                "moonwalker:configuration-listener",
            }
            | ({"moonwalker:accumulation"} if with_accumulation else set())
        )
        assert fake_database.run_calls[:2] == [
            "instance",
            "reconcile_placement_intents",
        ]
        assert "backfill_trade_replay_candles_if_needed" in fake_database.run_calls
        assert "_listen" in fake_database.run_calls
        assert not hasattr(app_module.runtime_state, "sidestep_campaign_service")
        assert fake_market_cap_service.start_calls == 1
        if accumulation is not None:
            assert accumulation.startup_calls == 1
            assert accumulation.running
            assert (
                app_module.runtime_state.placement_recovery.accumulation_recovery
                == accumulation.recovery.reconcile
            )
        assert app_module.runtime_state.controller_services is not None
        assert app_module.runtime_state.controller_services.accumulation is accumulation
        assert (
            app_module.runtime_state.controller_services.order_lifecycle
            is app_module.runtime_state.placement_recovery.dca
        )

    assert fake_market_cap_service.shutdown_calls == 1
    assert app_module.runtime_state.controller_services is None
    if accumulation is not None:
        assert accumulation.closed and not accumulation.running
        assert app_module.runtime_state.accumulation_runtime is None


def _patch_startup_gate_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    recovery_factory: type,
) -> None:
    """Patch the globals startup touches before the placement reconciliation gate."""
    monkeypatch.setattr(app_module, "runtime_state", app_module.RuntimeState())
    monkeypatch.setattr(app_module, "start_redis", lambda: object())
    monkeypatch.setattr(app_module, "redis_client", _FakeRedisClient())
    monkeypatch.setattr(
        app_module,
        "coin_market_cap_rank_service",
        _FakeMarketCapRankService(),
    )
    monkeypatch.setattr(app_module, "Database", lambda: _FakeDatabase())
    monkeypatch.setattr(app_module, "PlacementRecoveryEntry", recovery_factory)
    monkeypatch.setattr(app_module, "Config", _FakeConfigFactory)
    monkeypatch.setattr(
        app_module, "build_accumulation_runtime", lambda _provider: None
    )
    # The gate paths never start the fanouts, but shutdown stops them; a
    # stop on the shared fanouts would mark them stopped for later tests.
    for controller in (
        app_module.trades_controller,
        app_module.statistics_controller,
    ):
        monkeypatch.setattr(controller, "start_websocket_fanout", _noop_async)
        monkeypatch.setattr(controller, "stop_websocket_fanout", _noop_async)


@pytest.mark.asyncio
async def test_lifespan_serves_placement_recovery_when_only_quarantined_intents_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quarantined-only classic-DCA work must serve recovery, not crash."""

    class _QuarantinedSummary(_FakePlacementSummary):
        ready = False
        action_required = ("limit_sell-abc123",)

    class _QuarantinedRecovery(_FakePlacementRecovery):
        async def reconcile_placement_intents(self, _config):
            return _QuarantinedSummary()

    _patch_startup_gate_dependencies(monkeypatch, _QuarantinedRecovery)

    async with app_module.runtime_lifespan(None):
        assert app_module.runtime_state.recovery_mode == "placement"
        assert app_module.runtime_state.controller_services is not None
        assert app_module.runtime_state.background_tasks == []
        assert app_module.runtime_state.watcher is None
        assert app_module.runtime_state.signal_plugin is None

    assert app_module.runtime_state.controller_services is None
    assert app_module.runtime_state.recovery_mode == "placement"


@pytest.mark.asyncio
async def test_lifespan_stays_fatal_when_nonterminal_work_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quarantined intent plus leftover nonterminal work keeps the crash gate."""

    class _MixedSummary(_FakePlacementSummary):
        ready = False
        action_required = ("limit_sell-abc123",)
        remaining = 1

    class _MixedRecovery(_FakePlacementRecovery):
        async def reconcile_placement_intents(self, _config):
            return _MixedSummary()

    _patch_startup_gate_dependencies(monkeypatch, _MixedRecovery)

    with pytest.raises(RuntimeError, match="requires operator action"):
        async with app_module.runtime_lifespan(None):
            pass

    assert app_module.runtime_state.recovery_mode is None
    assert app_module.runtime_state.controller_services is None


@pytest.mark.asyncio
async def test_recovery_middleware_gates_placement_recovery_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Placement recovery mode allows exactly the recovery reads and actions."""
    monkeypatch.setattr(app_module, "runtime_state", app_module.RuntimeState())
    app_module.runtime_state.recovery_mode = "placement"
    served: list[str] = []

    @get(path="/orders/placement-recovery")
    async def list_recovery() -> dict[str, list[str]]:
        served.append("list")
        return {"intents": []}

    @post(
        path="/orders/placement-recovery/{operation_id:str}/repair",
        status_code=200,
    )
    async def repair_one(operation_id: FromPath[str]) -> dict[str, str]:
        served.append(f"repair:{operation_id}")
        return {"status": "unchanged"}

    @post(
        path="/orders/placement-recovery/{operation_id:str}/dismiss",
        status_code=200,
    )
    async def dismiss_one(operation_id: FromPath[str]) -> dict[str, str]:
        served.append(f"dismiss:{operation_id}")
        return {"status": "dismissed"}

    @get(path="/trades/open")
    async def forbidden_history() -> dict[str, bool]:
        served.append("history")
        return {"read": True}

    @post(path="/orders/sell/BTC/USDC", status_code=200)
    async def forbidden_sale() -> dict[str, bool]:
        served.append("sell")
        return {"sold": True}

    app = Litestar(
        route_handlers=[
            list_recovery,
            repair_one,
            dismiss_one,
            forbidden_history,
            forbidden_sale,
        ],
        middleware=[app_module.RecoveryOnlyMiddleware()],
        openapi_config=None,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost"
    ) as http:
        assert (await http.get("/orders/placement-recovery")).status_code == 200
        assert (
            await http.post("/orders/placement-recovery/op-1/repair")
        ).status_code == 200
        assert (
            await http.post(
                "/orders/placement-recovery/op-1/dismiss", json={"note": "n"}
            )
        ).status_code == 200
        for method, path, expected in (
            ("GET", "/trades/open", 503),
            ("POST", "/orders/sell/BTC/USDC", 409),
        ):
            rejected = await http.request(method, path, json={})
            assert rejected.status_code == expected
            assert rejected.json()["code"] == "recovery_only"
        # Unmatched paths return 404 before any middleware runs in
        # Litestar, so a non-action path under the recovery namespace is
        # still unreachable.
        missing = await http.post(
            "/orders/placement-recovery/op-1/unknown-action", json={}
        )
        assert missing.status_code == 404
        assert served == ["list", "repair:op-1", "dismiss:op-1"]

        downstream = Mock()
        sent = AsyncMock()
        await app_module.RecoveryOnlyMiddleware()(downstream)(
            {"type": "websocket", "path": "/trades/open"}, Mock(), sent
        )
        sent.assert_awaited_once_with({"type": "websocket.close", "code": 1013})
        downstream.assert_not_called()


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

    class OrderedConfig:
        async def _listen(self) -> None:
            await owned_loop("configuration-listener")

        async def stop_listener(self) -> None:
            events.append("configuration:stop")

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
        def __init__(self, name: str) -> None:
            self.name = name

        async def start(self, _task_group) -> None:
            events.append(f"{self.name}:start")

        async def stop(self) -> None:
            events.append(f"{self.name}:stop")

    class OrderedProvider:
        async def start(self) -> None:
            events.append("provider:start")

        async def close(self) -> None:
            events.append("provider:close")

    class OrderedRedis:
        async def aclose(self) -> None:
            events.append("redis:close")

    state = app_module.RuntimeState()
    shared_redis_process = Mock()

    async def ordered_startup() -> None:
        events.append("startup")
        state.redis_proc = shared_redis_process
        state.watcher_queue = asyncio.Queue()
        state.database = OrderedDatabase()
        state.config_service = OrderedConfig()
        state.watcher = OrderedWatcher()
        state.housekeeper = OrderedHousekeeper()
        state.signal_plugin = OrderedSignal()

    async def recover_pending() -> None:
        events.append("recover")

    async def stop_trades_fanout() -> None:
        events.append("trades-fanout:stop")

    async def stop_statistics_fanout() -> None:
        events.append("statistics-fanout:stop")

    monkeypatch.setattr(app_module, "runtime_state", state)
    monkeypatch.setattr(app_module, "startup", ordered_startup)
    monkeypatch.setattr(app_module, "ai_work_queue", OrderedQueue("ai-queue"))
    monkeypatch.setattr(
        app_module,
        "replay_repair_queue",
        OrderedQueue("replay-repair-queue"),
    )
    monkeypatch.setattr(app_module, "ai_provider_client", OrderedProvider())
    monkeypatch.setattr(app_module, "redis_client", OrderedRedis())
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

    assert events.index("ai-queue:stop") < events.index("symbol-intake:done")
    assert events.index("replay-repair-queue:stop") < events.index("symbol-intake:done")
    for task_name in (
        "symbol-intake",
        "ticker-watcher",
        "housekeeping",
        "replay",
        "configuration-listener",
    ):
        assert events.index(f"{task_name}:done") < events.index("trades-fanout:stop")
    ordered_shutdown_events = [
        "trades-fanout:stop",
        "statistics-fanout:stop",
        "signal:shutdown",
        "watcher:shutdown",
        "housekeeper:shutdown",
        "configuration:stop",
        "database:shutdown",
        "provider:close",
        "redis:close",
    ]
    assert [event for event in events if event in ordered_shutdown_events] == (
        ordered_shutdown_events
    )
    shared_redis_process.terminate.assert_not_called()
    shared_redis_process.kill.assert_not_called()
    shared_redis_process.wait.assert_not_called()


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
        placement_recovery=CloseService("placement_recovery"),  # type: ignore[arg-type]
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
        "placement_recovery",
        "market_cap",
        "database",
        "provider",
        "redis",
    ]
    assert state.signal_plugin is None
    assert state.placement_recovery is None
    assert state.order_lifecycle is None
    assert state.database is None


class _FakeAccumulationRuntime:
    entry = object()

    def __init__(self):
        self.recovery = self
        self.startup_calls = 0
        self.running = False
        self.closed = False
        self.stopping = False

    async def reconcile(self, *_args):
        return "completed"

    async def startup(self):
        self.startup_calls += 1
        return True

    async def run(self):
        self.running = True
        try:
            await asyncio.Event().wait()
        finally:
            self.running = False

    def request_stop(self):
        self.stopping = True

    async def shutdown(self):
        assert self.stopping and not self.running
        self.closed = True
