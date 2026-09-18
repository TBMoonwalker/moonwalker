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


@pytest.mark.asyncio
async def test_detect_stalled_symbol_requests_reclaim_when_one_symbol_hung(monkeypatch):
    """F3: a single hung feed must be caught even while others keep trading."""
    watcher = Watcher()
    watcher.config = {"exchange": "binance"}
    monkeypatch.setattr(watcher_module, "logging", _Logger())
    watcher.STREAM_SILENCE_TIMEOUT_SECONDS = 0.5

    async def hung() -> None:
        await asyncio.sleep(10_000)

    async def alive() -> None:
        await asyncio.sleep(10_000)

    hung_task = asyncio.create_task(hung())
    alive_task = asyncio.create_task(alive())
    watcher.symbol_tasks = {"ETH/USDC": hung_task, "BTC/USDC": alive_task}
    now = time.monotonic()
    watcher._last_symbol_data_at = {
        "ETH/USDC": now - 100.0,
        "BTC/USDC": now,
    }
    watcher._reclaim_stream_requested = False

    detected = watcher._detect_stalled_symbol()

    assert detected is True
    assert watcher._reclaim_stream_requested is True

    for task in (hung_task, alive_task):
        task.cancel()
    await asyncio.gather(hung_task, alive_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_detect_stalled_symbol_ignores_done_tasks(monkeypatch):
    """A crashed task is left to the symbol-sync loop, not the heartbeat scan."""
    watcher = Watcher()
    watcher.config = {}
    monkeypatch.setattr(watcher_module, "logging", _Logger())
    watcher.STREAM_SILENCE_TIMEOUT_SECONDS = 0.5

    async def done_task() -> None:
        return None

    finished = asyncio.create_task(done_task())
    await asyncio.sleep(0.01)
    assert finished.done()

    watcher.symbol_tasks = {"X/USDC": finished}
    now = time.monotonic()
    watcher._last_symbol_data_at = {"X/USDC": now - 1.0}
    watcher._reclaim_stream_requested = False

    detected = watcher._detect_stalled_symbol()

    assert detected is False
    assert watcher._reclaim_stream_requested is False
    await finished


@pytest.mark.asyncio
async def test_detect_stalled_symbol_ignores_fresh_heartbeat(monkeypatch):
    """A live symbol with a recent read is not reclaimed even when stale window elapses."""
    watcher = Watcher()
    watcher.config = {}
    monkeypatch.setattr(watcher_module, "logging", _Logger())
    watcher.STREAM_SILENCE_TIMEOUT_SECONDS = 0.5

    async def alive() -> None:
        await asyncio.sleep(10_000)

    task = asyncio.create_task(alive())
    watcher.symbol_tasks = {"BTC/USDC": task}
    watcher._last_symbol_data_at = {"BTC/USDC": time.monotonic()}
    watcher._reclaim_stream_requested = False

    assert watcher._detect_stalled_symbol() is False
    assert watcher._reclaim_stream_requested is False

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_per_symbol_timeout_scales_with_timeframe_but_floored(monkeypatch):
    """A quiet large-timeframe feed waits a candle; short ones use the floor."""
    watcher = Watcher()
    monkeypatch.setattr(watcher_module, "logging", _Logger())
    watcher.STREAM_SILENCE_TIMEOUT_SECONDS = 1800.0

    watcher.runtime_state.timeframe = "1d"
    assert watcher._per_symbol_stale_timeout() == 86_400.0

    watcher.runtime_state.timeframe = "1m"
    assert watcher._per_symbol_stale_timeout() == 1800.0


@pytest.mark.asyncio
async def test_per_symbol_timeout_cap_blocks_multi_day_window(monkeypatch):
    """F3 regression: a long timeframe caps at one candle, not a multi-day window."""
    watcher = Watcher()
    monkeypatch.setattr(watcher_module, "logging", _Logger())
    watcher.STREAM_SILENCE_TIMEOUT_SECONDS = 1800.0

    watcher.runtime_state.timeframe = "1w"
    assert watcher._per_symbol_stale_timeout() == 7 * 86_400.0

    watcher.runtime_state.timeframe = "1d"
    assert watcher._per_symbol_stale_timeout() == 86_400.0


@pytest.mark.asyncio
async def test_reconcile_prunes_dropped_and_seeds_new(monkeypatch):
    """Heartbeats track the live symbol set: drop removed, seed freshly added."""
    watcher = Watcher()
    monkeypatch.setattr(watcher_module, "logging", _Logger())
    watcher._last_symbol_data_at = {"AAA/USDC": 1.0}

    async def alive() -> None:
        await asyncio.sleep(10_000)

    watcher.symbol_tasks = {"BBB/USDC": asyncio.create_task(alive())}

    watcher._reconcile_symbol_heartbeats()

    assert "AAA/USDC" not in watcher._last_symbol_data_at
    assert "BBB/USDC" in watcher._last_symbol_data_at

    watcher.symbol_tasks["BBB/USDC"].cancel()
    await asyncio.gather(*watcher.symbol_tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_watch_symbol_ohlcv_stamps_heartbeat(monkeypatch):
    """A successful watch_ohlcv read (data or not) refreshes that symbol's heartbeat."""
    watcher = Watcher()
    watcher.config = {"exchange": "binance"}
    monkeypatch.setattr(watcher_module, "logging", _Logger())
    watcher.runtime_state.exchange_watcher_ohlcv = True
    watcher.runtime_state.timeframe = "1m"

    async def fake_watch_ohlcv(_symbol, _timeframe):
        return [[1, 1, 1, 1, 1.0, 1]]

    watcher.exchange = type("E", (), {"watch_ohlcv": fake_watch_ohlcv})
    watcher._last_symbol_data_at = {}

    await watcher.watch_symbol("BTC/USDC")

    assert "BTC/USDC" in watcher._last_symbol_data_at


@pytest.mark.asyncio
async def test_watch_symbol_trades_stamps_heartbeat_even_when_empty(monkeypatch):
    """A quiet-but-alive trades feed still refreshes its heartbeat on an empty read."""
    watcher = Watcher()
    watcher.config = {"exchange": "binance"}
    monkeypatch.setattr(watcher_module, "logging", _Logger())
    watcher.runtime_state.exchange_watcher_ohlcv = False

    async def fake_watch_trades(_symbol):
        return []

    watcher.exchange = type("E", (), {"watch_trades": fake_watch_trades})
    watcher._last_symbol_data_at = {}

    await watcher.watch_symbol("ETH/USDC")

    assert "ETH/USDC" in watcher._last_symbol_data_at
