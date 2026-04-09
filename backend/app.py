"""Litestar application entry point."""

import asyncio
import importlib.util
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from controller import route_handlers
from controller import statistics as statistics_controller
from controller import trades as trades_controller
from litestar import Litestar
from litestar.config.compression import CompressionConfig
from litestar.config.cors import CORSConfig
from service.config import Config
from service.database import Database
from service.green_phase import GreenPhaseService
from service.housekeeper import Housekeeper
from service.redis import redis_client, start_redis, stop_redis
from service.signal import Signal
from service.watcher import Watcher


@dataclass
class RuntimeState:
    """Container for long-lived runtime services."""

    redis_proc: subprocess.Popen[bytes] | None = None
    watcher_queue: asyncio.Queue[Any] | None = None
    database: Database | None = None
    conf: Config | None = None
    watcher: Watcher | None = None
    housekeeper: Housekeeper | None = None
    green_phase_service: GreenPhaseService | None = None
    signal_plugin: Signal | None = None
    background_tasks: list[asyncio.Task[Any]] = field(default_factory=list)


runtime_state = RuntimeState()


async def startup() -> None:
    """Initialize core services and start background tasks before serving."""
    runtime_state.redis_proc = await asyncio.to_thread(start_redis)
    runtime_state.watcher_queue = asyncio.Queue()

    runtime_state.database = Database()
    await runtime_state.database.init()

    runtime_state.conf = await runtime_state.database.run_with_context(Config.instance)

    runtime_state.watcher = Watcher()
    await runtime_state.watcher.init()

    runtime_state.housekeeper = Housekeeper()
    await runtime_state.housekeeper.init()

    runtime_state.green_phase_service = await GreenPhaseService.instance()
    await runtime_state.green_phase_service.start()

    runtime_state.signal_plugin = Signal(runtime_state.watcher_queue)
    await runtime_state.database.run_with_context(runtime_state.signal_plugin.init)
    await trades_controller.start_websocket_fanout()
    await statistics_controller.start_websocket_fanout()

    runtime_state.background_tasks = [
        asyncio.create_task(
            runtime_state.database.run_with_context(
                runtime_state.watcher.watch_incoming_symbols,
                runtime_state.watcher_queue,
            )
        ),
        asyncio.create_task(
            runtime_state.database.run_with_context(
                runtime_state.housekeeper.cleanup_ticker_database
            )
        ),
        asyncio.create_task(
            runtime_state.database.run_with_context(runtime_state.watcher.watch_tickers)
        ),
        asyncio.create_task(
            runtime_state.database.run_with_context(
                runtime_state.database.backfill_trade_replay_candles_if_needed
            )
        ),
    ]


async def shutdown() -> None:
    """Gracefully stop background services and close external connections."""
    await trades_controller.stop_websocket_fanout()
    await statistics_controller.stop_websocket_fanout()

    for task in runtime_state.background_tasks:
        task.cancel()
    if runtime_state.background_tasks:
        await asyncio.gather(*runtime_state.background_tasks, return_exceptions=True)
    runtime_state.background_tasks.clear()

    if runtime_state.signal_plugin is not None:
        await runtime_state.signal_plugin.shutdown()
    if runtime_state.watcher is not None:
        await runtime_state.watcher.shutdown()
    if runtime_state.housekeeper is not None:
        await runtime_state.housekeeper.shutdown()
    if runtime_state.green_phase_service is not None:
        await runtime_state.green_phase_service.shutdown()
    if runtime_state.database is not None:
        await runtime_state.database.shutdown()

    await redis_client.aclose()

    if runtime_state.redis_proc is not None:
        await asyncio.to_thread(stop_redis, runtime_state.redis_proc)
        runtime_state.redis_proc = None


app = Litestar(
    route_handlers=route_handlers,
    cors_config=CORSConfig(
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    ),
    compression_config=CompressionConfig(
        backend="gzip",
        minimum_size=500,
        gzip_compress_level=6,
    ),
    on_startup=[startup],
    on_shutdown=[shutdown],
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
