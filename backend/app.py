"""Litestar application entry point."""

import asyncio
import importlib.util
import os
import subprocess
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import helper
import uvicorn
from controller import route_handlers
from controller import statistics as statistics_controller
from controller import trades as trades_controller
from litestar import Litestar
from litestar.config.compression import CompressionConfig
from litestar.config.cors import CORSConfig
from litestar.middleware import DefineMiddleware
from service.ai_provider import ai_provider_client
from service.ai_trust import recover_pending_outcome_attributions
from service.ai_work_queue import ai_work_queue
from service.autopilot_memory import AutopilotMemoryService
from service.coin_market_cap import (
    CoinMarketCapRankService,
    coin_market_cap_rank_service,
)
from service.config import Config
from service.database import Database
from service.delisting_protection import DelistingProtectionService
from service.green_phase import GreenPhaseService
from service.housekeeper import Housekeeper
from service.orders import Orders
from service.origin_policy import (
    TrustedLanHttpMiddleware,
    WebSocketOriginMiddleware,
    parse_allowed_hosts,
    parse_allowed_origins,
)
from service.redis import redis_client, start_redis, stop_redis
from service.replay_repair_queue import replay_repair_queue
from service.runtime_services import (
    RuntimeServices,
    activate_runtime_services,
    build_runtime_services,
    deactivate_runtime_services,
)
from service.signal import Signal
from service.watcher import Watcher

logging = helper.LoggerFactory.get_logger("logs/startup.log", "startup")
ALLOWED_ORIGINS = parse_allowed_origins(os.getenv("MOONWALKER_ALLOWED_ORIGINS"))
ALLOWED_HOSTS = parse_allowed_hosts(os.getenv("MOONWALKER_ALLOWED_HOSTS"))


@dataclass
class RuntimeState:
    """Container for long-lived runtime services."""

    redis_proc: subprocess.Popen[bytes] | None = None
    watcher_queue: asyncio.Queue[Any] | None = None
    database: Database | None = None
    market_cap_rank_service: CoinMarketCapRankService | None = None
    controller_services: RuntimeServices | None = None
    placement_orders: Orders | None = None
    watcher: Watcher | None = None
    housekeeper: Housekeeper | None = None
    green_phase_service: GreenPhaseService | None = None
    delisting_protection_service: DelistingProtectionService | None = None
    autopilot_memory_service: AutopilotMemoryService | None = None
    signal_plugin: Signal | None = None
    background_tasks: list[asyncio.Task[Any]] = field(default_factory=list)


runtime_state = RuntimeState()


class RuntimeShutdownError(RuntimeError):
    """Aggregate ordinary cleanup failures after all resources were attempted."""

    def __init__(self, failures: list[Exception]) -> None:
        self.failures = tuple(failures)
        super().__init__(f"Moonwalker shutdown failed in {len(failures)} step(s)")


async def _run_startup_step(
    name: str,
    operation: Callable[[], Awaitable[Any]],
) -> Any:
    """Run one startup operation and log how long it blocks readiness."""
    started_at = time.perf_counter()
    logging.info("Startup step started: %s", name)
    try:
        result = await operation()
    except Exception:
        logging.exception(
            "Startup step failed: %s after %.3fs",
            name,
            time.perf_counter() - started_at,
        )
        raise

    logging.info(
        "Startup step finished: %s in %.3fs",
        name,
        time.perf_counter() - started_at,
    )
    return result


async def startup() -> None:
    """Initialize core services before the lifespan starts runtime tasks."""
    started_at = time.perf_counter()
    logging.info("Moonwalker startup sequence started.")
    try:
        runtime_state.redis_proc = await _run_startup_step(
            "redis start",
            lambda: asyncio.to_thread(start_redis),
        )
        runtime_state.watcher_queue = asyncio.Queue()

        runtime_state.database = Database()
        await _run_startup_step("database init", runtime_state.database.init)

        config_service = await _run_startup_step(
            "config load",
            lambda: runtime_state.database.run_with_context(Config.instance),
        )

        runtime_state.market_cap_rank_service = coin_market_cap_rank_service
        await _run_startup_step(
            "CoinMarketCap rank service start",
            runtime_state.market_cap_rank_service.start,
        )

        runtime_state.placement_orders = Orders()
        reconciliation = await _run_startup_step(
            "exchange placement reconciliation",
            lambda: runtime_state.database.run_with_context(
                runtime_state.placement_orders.reconcile_placement_intents,
                config_service.snapshot(),
            ),
        )
        if not reconciliation.ready:
            operations = ", ".join(reconciliation.action_required)
            raise RuntimeError(
                "Exchange placement reconciliation requires operator action "
                f"before trading can start: {operations}"
            )

        runtime_state.watcher = Watcher()
        await _run_startup_step("watcher init", runtime_state.watcher.init)

        runtime_state.housekeeper = Housekeeper()
        await _run_startup_step("housekeeper init", runtime_state.housekeeper.init)

        runtime_state.green_phase_service = await _run_startup_step(
            "green phase init",
            GreenPhaseService.instance,
        )
        await _run_startup_step(
            "green phase start",
            runtime_state.green_phase_service.start,
        )

        runtime_state.autopilot_memory_service = await _run_startup_step(
            "autopilot memory init",
            AutopilotMemoryService.instance,
        )
        await _run_startup_step(
            "autopilot memory start",
            runtime_state.autopilot_memory_service.start,
        )

        runtime_state.delisting_protection_service = await _run_startup_step(
            "delisting protection init",
            DelistingProtectionService.instance,
        )
        await _run_startup_step(
            "delisting protection start",
            runtime_state.delisting_protection_service.start,
        )

        assert runtime_state.placement_orders is not None
        runtime_state.controller_services = build_runtime_services(
            orders=runtime_state.placement_orders,
            delisting_protection=runtime_state.delisting_protection_service,
            statistics_balance_cache_ttl_seconds=(
                statistics_controller.STATISTICS_BALANCE_CACHE_TTL_SECONDS
            ),
        )
        activate_runtime_services(runtime_state.controller_services)

        runtime_state.signal_plugin = Signal(runtime_state.watcher_queue)
        await _run_startup_step(
            "signal plugin init",
            lambda: runtime_state.database.run_with_context(
                runtime_state.signal_plugin.init
            ),
        )
        await _run_startup_step(
            "trades websocket fanout start",
            trades_controller.start_websocket_fanout,
        )
        await _run_startup_step(
            "statistics websocket fanout start",
            statistics_controller.start_websocket_fanout,
        )

    except Exception:
        logging.exception(
            "Moonwalker startup sequence failed after %.3fs",
            time.perf_counter() - started_at,
        )
        raise

    logging.info(
        "Moonwalker startup sequence finished in %.3fs",
        time.perf_counter() - started_at,
    )


async def shutdown() -> None:
    """Gracefully stop background services and close external connections."""
    failures: list[Exception] = []

    async def attempt(
        name: str,
        operation: Callable[[], Awaitable[None]],
    ) -> None:
        try:
            await operation()
        except Exception as exc:  # noqa: BLE001 - cleanup must continue.
            logging.exception("Shutdown step failed: %s", name)
            failures.append(exc)

    await attempt(
        "trades websocket fanout",
        trades_controller.stop_websocket_fanout,
    )
    await attempt(
        "statistics websocket fanout",
        statistics_controller.stop_websocket_fanout,
    )

    if runtime_state.signal_plugin is not None:
        await attempt("signal plugin", runtime_state.signal_plugin.shutdown)
        runtime_state.signal_plugin = None

    for task in runtime_state.background_tasks:
        task.cancel()
    if runtime_state.background_tasks:
        await asyncio.gather(*runtime_state.background_tasks, return_exceptions=True)
    runtime_state.background_tasks.clear()

    if runtime_state.watcher is not None:
        await attempt("watcher", runtime_state.watcher.shutdown)
        runtime_state.watcher = None
    if runtime_state.housekeeper is not None:
        await attempt("housekeeper", runtime_state.housekeeper.shutdown)
        runtime_state.housekeeper = None
    if runtime_state.green_phase_service is not None:
        await attempt("green phase", runtime_state.green_phase_service.shutdown)
        runtime_state.green_phase_service = None
    if runtime_state.autopilot_memory_service is not None:
        await attempt(
            "autopilot memory",
            runtime_state.autopilot_memory_service.shutdown,
        )
        runtime_state.autopilot_memory_service = None
    if runtime_state.delisting_protection_service is not None:
        await attempt(
            "delisting protection",
            runtime_state.delisting_protection_service.shutdown,
        )
        runtime_state.delisting_protection_service = None
    if runtime_state.controller_services is not None:
        controller_services = runtime_state.controller_services
        await attempt("controller services", controller_services.shutdown)
        deactivate_runtime_services(controller_services)
        runtime_state.controller_services = None
        runtime_state.placement_orders = None
    elif runtime_state.placement_orders is not None:
        await attempt("placement orders", runtime_state.placement_orders.close)
        runtime_state.placement_orders = None
    if runtime_state.market_cap_rank_service is not None:
        await attempt(
            "CoinMarketCap rank service",
            runtime_state.market_cap_rank_service.shutdown,
        )
        runtime_state.market_cap_rank_service = None
    if runtime_state.database is not None:
        await attempt("database", runtime_state.database.shutdown)
        runtime_state.database = None

    await attempt("AI provider", ai_provider_client.close)
    await attempt("Redis client", redis_client.aclose)

    if runtime_state.redis_proc is not None:
        redis_proc = runtime_state.redis_proc
        await attempt(
            "Redis process",
            lambda: asyncio.to_thread(stop_redis, redis_proc),
        )
        runtime_state.redis_proc = None
    runtime_state.watcher_queue = None

    if failures:
        raise RuntimeShutdownError(failures)


async def _run_critical_runtime_task(
    name: str,
    operation: Callable[[], Awaitable[Any]],
) -> None:
    """Run a critical loop and fail the lifespan if it exits unexpectedly."""
    try:
        await operation()
    except asyncio.CancelledError:
        raise
    except Exception:
        logging.exception("Critical runtime task failed: %s", name)
        raise
    current_task = asyncio.current_task()
    if current_task is not None and current_task.cancelling():
        raise asyncio.CancelledError
    raise RuntimeError(f"Critical runtime task exited unexpectedly: {name}")


async def _run_optional_runtime_task(
    name: str,
    operation: Callable[[], Awaitable[Any]],
) -> None:
    """Run optional background work without taking down the trading runtime."""
    try:
        await operation()
    except asyncio.CancelledError:
        raise
    except Exception:
        logging.exception("Optional runtime task failed: %s", name)


async def _finish_cleanup_despite_cancellation(
    operation: Awaitable[None],
) -> None:
    """Finish cleanup even when the hosting lifespan task is cancelled."""
    cleanup_task = asyncio.create_task(
        operation,
        name="moonwalker:runtime-shutdown",
    )
    current_task = asyncio.current_task()

    while not cleanup_task.done():
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            if cleanup_task.done():
                await cleanup_task
            if current_task is not None:
                current_task.uncancel()

    await cleanup_task


@asynccontextmanager
async def runtime_lifespan(_app: Litestar) -> AsyncIterator[None]:
    """Own runtime tasks and services for exactly one application lifespan."""
    try:
        await startup()
        await ai_provider_client.start()
        assert runtime_state.database is not None
        assert runtime_state.watcher is not None
        assert runtime_state.housekeeper is not None
        assert runtime_state.watcher_queue is not None

        # Ownership:
        # lifespan
        # |-- critical: symbol intake, ticker watcher, housekeeping
        # `-- optional: replay-candle backfill
        async with asyncio.TaskGroup() as task_group:
            await ai_work_queue.start(task_group)
            await replay_repair_queue.start(task_group)
            await runtime_state.database.run_with_context(
                recover_pending_outcome_attributions
            )
            runtime_state.background_tasks = [
                task_group.create_task(
                    _run_critical_runtime_task(
                        "symbol-intake",
                        lambda: runtime_state.database.run_with_context(
                            runtime_state.watcher.watch_incoming_symbols,
                            runtime_state.watcher_queue,
                        ),
                    ),
                    name="moonwalker:symbol-intake",
                ),
                task_group.create_task(
                    _run_critical_runtime_task(
                        "ticker-watcher",
                        lambda: runtime_state.database.run_with_context(
                            runtime_state.watcher.watch_tickers
                        ),
                    ),
                    name="moonwalker:ticker-watcher",
                ),
                task_group.create_task(
                    _run_critical_runtime_task(
                        "housekeeping",
                        lambda: runtime_state.database.run_with_context(
                            runtime_state.housekeeper.cleanup_ticker_database
                        ),
                    ),
                    name="moonwalker:housekeeping",
                ),
                task_group.create_task(
                    _run_optional_runtime_task(
                        "replay-candle-backfill",
                        lambda: runtime_state.database.run_with_context(
                            runtime_state.database.backfill_trade_replay_candles_if_needed
                        ),
                    ),
                    name="moonwalker:replay-candle-backfill",
                ),
            ]
            try:
                yield
            finally:
                await ai_work_queue.stop()
                await replay_repair_queue.stop()
                for task in runtime_state.background_tasks:
                    task.cancel()
    finally:
        await _finish_cleanup_despite_cancellation(shutdown())


app = Litestar(
    route_handlers=route_handlers,
    cors_config=CORSConfig(
        allow_origins=list(ALLOWED_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    ),
    middleware=[
        DefineMiddleware(
            TrustedLanHttpMiddleware,
            allowed_origins=ALLOWED_ORIGINS,
            allowed_hosts=ALLOWED_HOSTS,
        ),
        DefineMiddleware(
            WebSocketOriginMiddleware,
            allowed_origins=ALLOWED_ORIGINS,
            allowed_hosts=ALLOWED_HOSTS,
        ),
    ],
    compression_config=CompressionConfig(
        backend="gzip",
        minimum_size=500,
        gzip_compress_level=6,
    ),
    lifespan=[runtime_lifespan],
)


def _env_int(name: str, default: int) -> int:
    """Read integer env value with fallback for invalid input."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """Read float env value with fallback for invalid input."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Read bool env value with fallback for invalid input."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _select_loop_backend() -> str:
    """Select best available event loop backend."""
    if importlib.util.find_spec("uvloop") is not None:
        return "uvloop"
    return "asyncio"


def _select_http_backend() -> str:
    """Select best available HTTP protocol backend."""
    if importlib.util.find_spec("httptools") is not None:
        return "httptools"
    return "h11"


def _select_ws_backend() -> str:
    """Select websocket protocol backend preferring sansio implementation."""
    if importlib.util.find_spec("websockets") is not None:
        return "websockets-sansio"
    if importlib.util.find_spec("wsproto") is not None:
        return "wsproto"
    return "auto"


def _build_uvicorn_kwargs(port: int) -> dict[str, Any]:
    """Build tuned and env-overridable Uvicorn runtime options."""
    limit_concurrency = _env_int("MOONWALKER_UVICORN_LIMIT_CONCURRENCY", 0) or None
    return {
        "host": os.getenv("MOONWALKER_HOST", "0.0.0.0"),
        "port": port,
        # Keep a single process: runtime services use in-memory shared state.
        "workers": 1,
        "loop": os.getenv("MOONWALKER_UVICORN_LOOP", _select_loop_backend()),
        "http": os.getenv("MOONWALKER_UVICORN_HTTP", _select_http_backend()),
        "ws": os.getenv("MOONWALKER_UVICORN_WS", _select_ws_backend()),
        "ws_ping_interval": _env_float("MOONWALKER_UVICORN_WS_PING_INTERVAL", 20.0),
        "ws_ping_timeout": _env_float("MOONWALKER_UVICORN_WS_PING_TIMEOUT", 20.0),
        "ws_max_queue": _env_int("MOONWALKER_UVICORN_WS_MAX_QUEUE", 64),
        "ws_per_message_deflate": _env_bool(
            "MOONWALKER_UVICORN_WS_PER_MESSAGE_DEFLATE", True
        ),
        "timeout_keep_alive": _env_int("MOONWALKER_UVICORN_TIMEOUT_KEEP_ALIVE", 10),
        "timeout_graceful_shutdown": _env_int(
            "MOONWALKER_UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN", 30
        ),
        "backlog": _env_int("MOONWALKER_UVICORN_BACKLOG", 2048),
        "limit_concurrency": limit_concurrency,
        "proxy_headers": _env_bool("MOONWALKER_UVICORN_PROXY_HEADERS", True),
        "access_log": _env_bool("MOONWALKER_UVICORN_ACCESS_LOG", False),
        "server_header": _env_bool("MOONWALKER_UVICORN_SERVER_HEADER", False),
        "date_header": _env_bool("MOONWALKER_UVICORN_DATE_HEADER", False),
    }


if __name__ == "__main__":
    port = int(os.getenv("MOONWALKER_PORT", "8130"))
    uvicorn.run(app, **_build_uvicorn_kwargs(port))
