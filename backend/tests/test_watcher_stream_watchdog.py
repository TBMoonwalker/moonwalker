import asyncio
import time

import pytest
import service.watcher as watcher_module
from service.watcher import Watcher


class _Logger:
    def __init__(self) -> None:
        self.warn: list[tuple[object, ...]] = []

    def warning(self, message: str, *args: object) -> None:
        self.warn.append((message, *args))

    def error(self, message: str, *args: object, **kwargs: object) -> None:
        self.warn.append((message, *args))

    def info(self, message: str, *args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_stream_watchdog_requests_reclaim_when_stream_silent(monkeypatch) -> None:
    watcher = Watcher()
    watcher.config = {"exchange": "binance", "market": "spot"}
    monkeypatch.setattr(watcher_module, "logging", _Logger())

    watcher.STREAM_WATCHDOG_CHECK_INTERVAL_SECONDS = 0.01
    watcher.STREAM_SILENCE_TIMEOUT_SECONDS = 0.05

    async def hung_watch() -> None:
        await asyncio.sleep(10_000)

    watcher.symbol_tasks = {
        "BTC/USDC": asyncio.create_task(hung_watch()),
        "ETH/USDC": asyncio.create_task(hung_watch()),
    }
    watcher.status = True
    watcher._last_stream_event_at = time.monotonic()
    watcher._reclaim_stream_requested = False

    watchdog = asyncio.create_task(watcher._stream_watchdog())
    await asyncio.sleep(0.2)

    assert watcher._reclaim_stream_requested is True

    watcher.status = False
    watchdog.cancel()
    await asyncio.gather(watchdog, return_exceptions=True)
    for task in watcher.symbol_tasks.values():
        task.cancel()
    await asyncio.gather(*watcher.symbol_tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_stream_watchdog_ignores_healthy_stream(monkeypatch) -> None:
    watcher = Watcher()
    watcher.config = {"exchange": "binance"}
    monkeypatch.setattr(watcher_module, "logging", _Logger())

    watcher.STREAM_WATCHDOG_CHECK_INTERVAL_SECONDS = 0.01
    watcher.STREAM_SILENCE_TIMEOUT_SECONDS = 0.10

    async def alive_symbol() -> None:
        await asyncio.sleep(10_000)

    watcher.symbol_tasks = {"BTC/USDC": asyncio.create_task(alive_symbol())}
    watcher.status = True
    watcher._reclaim_stream_requested = False

    watchdog = asyncio.create_task(watcher._stream_watchdog())

    for _ in range(6):
        await asyncio.sleep(0.02)
        watcher._last_stream_event_at = time.monotonic()

    assert watcher._reclaim_stream_requested is False

    watcher.status = False
    watchdog.cancel()
    await asyncio.gather(watchdog, return_exceptions=True)
    watcher.symbol_tasks["BTC/USDC"].cancel()
    await asyncio.gather(watcher.symbol_tasks["BTC/USDC"], return_exceptions=True)


@pytest.mark.asyncio
async def test_drain_reclaim_rebuilds_client_and_respawns(monkeypatch) -> None:
    watcher = Watcher()
    watcher.config = {"exchange": "binance", "market": "spot", "dry_run": True}
    monkeypatch.setattr(watcher_module, "logging", _Logger())
    watcher.status = True

    rebuilt: list[str] = []

    async def fake_reload(_config: dict) -> None:
        rebuilt.append("reload")
        watcher.exchange = None

    async def fake_cancel() -> None:
        watcher.symbol_tasks = {}

    async def fake_sync() -> None:
        watcher.symbol_tasks = {}

    watcher._reload_exchange_client = fake_reload  # type: ignore[assignment]
    watcher._cancel_symbol_tasks = fake_cancel  # type: ignore[assignment]
    watcher._Watcher__sync_symbol_tasks = fake_sync  # type: ignore[assignment]

    watcher._reclaim_stream_requested = True
    await watcher._drain_reclaim_request()

    assert watcher._reclaim_stream_requested is False
    assert "reload" in rebuilt
    assert watcher.symbol_tasks == {}


@pytest.mark.asyncio
async def test_drain_reclaim_is_noop_without_pending_request(monkeypatch) -> None:
    watcher = Watcher()
    watcher.config = {}
    monkeypatch.setattr(watcher_module, "logging", _Logger())
    watcher.status = True

    called: list[str] = []

    async def fake_reload(_config: dict) -> None:
        called.append("reload")

    async def fake_cancel() -> None:
        watcher.symbol_tasks.clear()

    async def fake_sync() -> None:
        watcher.symbol_tasks = {}

    watcher._reload_exchange_client = fake_reload  # type: ignore[assignment]
    watcher._cancel_symbol_tasks = fake_cancel  # type: ignore[assignment]
    watcher._Watcher__sync_symbol_tasks = fake_sync  # type: ignore[assignment]

    watcher._reclaim_stream_requested = False
    await watcher._drain_reclaim_request()

    assert "reload" not in called
    assert watcher._reclaim_stream_requested is False


@pytest.mark.asyncio
async def test_reclaim_failure_does_not_propagate(monkeypatch) -> None:
    """F1 regression: a failing reclaim must be absorbed, not crash the loop.

    The reclaim runs inside the main loop, so an exchange-client rebuild that
    raises (misconfigured exchange name or a ccxt-pro error) must not
    propagate and kill the ticker-watcher task it exists to keep alive.
    """
    watcher = Watcher()
    watcher.config = {}
    monkeypatch.setattr(watcher_module, "logging", _Logger())
    watcher.status = True

    async def failing_reclaim() -> None:
        raise AttributeError("exchange not configured")

    watcher._reclaim_stalled_stream = failing_reclaim  # type: ignore[assignment]
    watcher._reclaim_stream_requested = True

    try:
        await watcher._drain_reclaim_request()
        propagated = False
    except AttributeError:
        propagated = True

    assert propagated is False
    assert watcher._reclaim_stream_requested is False
