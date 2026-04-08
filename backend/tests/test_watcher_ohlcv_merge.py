import asyncio

import pytest
import service.watcher as watcher_module
from service.watcher import Watcher


def test_prepare_ohlcv_write_merges_same_timestamp() -> None:
    watcher = Watcher()
    symbol = "BTC/USDC"

    first = [1_000, 10.0, 10.0, 10.0, 10.0, 1.0]
    assert watcher._Watcher__prepare_ohlcv_write(symbol, [first]) is None

    second = [1_000, 11.0, 12.0, 9.0, 11.0, 0.5]
    assert watcher._Watcher__prepare_ohlcv_write(symbol, [second]) is None

    assert watcher.runtime_state.candles[symbol] == [
        1000.0,
        10.0,
        12.0,
        9.0,
        11.0,
        1.5,
    ]


def test_prepare_ohlcv_write_returns_merged_payload_on_rollover() -> None:
    watcher = Watcher()
    symbol = "BTC/USDC"

    first = [1_000, 10.0, 10.0, 10.0, 10.0, 1.0]
    second = [1_000, 11.0, 12.0, 9.0, 11.0, 0.5]
    next_candle = [2_000, 11.0, 13.0, 10.0, 12.0, 2.0]

    watcher._Watcher__prepare_ohlcv_write(symbol, [first])
    watcher._Watcher__prepare_ohlcv_write(symbol, [second])
    payload = watcher._Watcher__prepare_ohlcv_write(symbol, [next_candle])

    assert payload == {
        "timestamp": 1000.0,
        "symbol": symbol,
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 1.5,
    }
    assert watcher.runtime_state.candles[symbol] == next_candle


def test_get_live_candle_snapshot_returns_a_copy() -> None:
    watcher = Watcher()
    watcher.runtime_state.candles["BTC/USDC"] = [1_000, 1, 2, 0.5, 1.5, 7]

    snapshot = Watcher.get_live_candle_snapshot("BTC/USDC")

    assert snapshot == [1_000, 1, 2, 0.5, 1.5, 7]
    assert snapshot is not watcher.runtime_state.candles["BTC/USDC"]


@pytest.mark.asyncio
async def test_dca_worker_survives_recoverable_processing_exception() -> None:
    watcher = Watcher()
    watcher.config = {}
    calls: list[float] = []

    async def fake_process_ticker_data(ticker_price: dict, config: dict) -> None:
        calls.append(float(ticker_price["ticker"]["price"]))
        if len(calls) == 1:
            raise ValueError("recoverable")
        watcher.status = False

    watcher.dca.process_ticker_data = fake_process_ticker_data
    worker = asyncio.create_task(watcher._process_dca_queue())

    watcher._queue_dca_payload(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 1.0}}
    )
    watcher._queue_dca_payload(
        {"type": "ticker_price", "ticker": {"symbol": "ETH/USDC", "price": 2.0}}
    )

    await asyncio.wait_for(worker, timeout=2)

    assert calls == [1.0, 2.0]
    assert watcher.dca_queue.qsize() == 0


@pytest.mark.asyncio
async def test_dca_worker_crashes_on_unexpected_processing_exception_and_restarts() -> (
    None
):
    watcher = Watcher()
    watcher.config = {}
    calls: list[float] = []

    async def fake_process_ticker_data(ticker_price: dict, config: dict) -> None:
        calls.append(float(ticker_price["ticker"]["price"]))
        if len(calls) == 1:
            raise KeyError("unexpected")
        watcher.status = False

    watcher.dca.process_ticker_data = fake_process_ticker_data
    worker = asyncio.create_task(
        watcher._process_dca_queue(), name=watcher.DCA_WORKER_TASK_NAME
    )
    watcher._worker_tasks = [worker]

    watcher._queue_dca_payload(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 1.0}}
    )
    watcher._queue_dca_payload(
        {"type": "ticker_price", "ticker": {"symbol": "ETH/USDC", "price": 2.0}}
    )

    with pytest.raises(KeyError, match="unexpected"):
        await asyncio.wait_for(worker, timeout=2)

    watcher._ensure_worker_tasks()
    replacement = watcher._worker_tasks[0]

    assert replacement is not worker
    await asyncio.wait_for(replacement, timeout=2)

    assert calls == [1.0, 2.0]
    assert watcher.dca_queue.qsize() == 0


@pytest.mark.asyncio
async def test_dca_queue_coalesces_pending_updates_per_symbol() -> None:
    watcher = Watcher()
    watcher.config = {}
    processed: list[float] = []
    release_processing = asyncio.Event()
    started_processing = asyncio.Event()

    async def fake_process_ticker_data(ticker_price: dict, config: dict) -> None:
        processed.append(float(ticker_price["ticker"]["price"]))
        started_processing.set()
        if len(processed) == 1:
            await release_processing.wait()
        else:
            watcher.status = False

    watcher.dca.process_ticker_data = fake_process_ticker_data
    worker = asyncio.create_task(watcher._process_dca_queue())

    watcher._queue_dca_payload(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 1.0}}
    )
    await asyncio.wait_for(started_processing.wait(), timeout=1)
    watcher._queue_dca_payload(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 2.0}}
    )
    watcher._queue_dca_payload(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 3.0}}
    )

    assert watcher.dca_queue.qsize() == 1

    release_processing.set()
    await asyncio.wait_for(worker, timeout=2)

    assert processed == [1.0, 3.0]
    assert watcher.dca_queue.qsize() == 0


@pytest.mark.asyncio
async def test_dca_queue_handoff_delivers_latest_payload_and_config() -> None:
    watcher = Watcher()
    watcher.config = {"timezone": "Europe/Vienna", "dry_run": True}
    delivered: list[tuple[dict[str, object], dict[str, object] | None]] = []

    async def fake_process_ticker_data(
        ticker_price: dict[str, object],
        config: dict[str, object] | None,
    ) -> None:
        delivered.append((ticker_price, config))
        watcher.status = False

    watcher.dca.process_ticker_data = fake_process_ticker_data
    watcher._queue_dca_payload(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 1.0}}
    )
    watcher._queue_dca_payload(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 2.0}}
    )

    worker = asyncio.create_task(watcher._process_dca_queue())
    await asyncio.wait_for(worker, timeout=2)

    assert delivered == [
        (
            {
                "type": "ticker_price",
                "ticker": {"symbol": "BTC/USDC", "price": 2.0},
            },
            watcher.config,
        )
    ]
    assert watcher.dca_queue.qsize() == 0


@pytest.mark.asyncio
async def test_dca_queue_overflow_drops_new_payload_with_warning(monkeypatch) -> None:
    watcher = Watcher()
    watcher.dca_queue = asyncio.Queue(maxsize=1)
    warnings: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        watcher_module.logging,
        "warning",
        lambda *args, **_kwargs: warnings.append(args),
    )

    watcher._queue_dca_payload(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 1.0}}
    )
    watcher._queue_dca_payload(
        {"type": "ticker_price", "ticker": {"symbol": "ETH/USDC", "price": 2.0}}
    )

    assert watcher.dca_queue.qsize() == 1
    assert "BTC/USDC" in watcher._pending_dca_payloads
    assert "ETH/USDC" not in watcher._pending_dca_payloads
    assert warnings == [
        (
            "dca queue full; dropping event for %s. qsize=%s workers=[%s]",
            "ETH/USDC",
            1,
            "none",
        )
    ]


@pytest.mark.asyncio
async def test_ensure_worker_tasks_restarts_crashed_dca_worker() -> None:
    watcher = Watcher()

    async def crash() -> None:
        raise RuntimeError("boom")

    crashed_task = asyncio.create_task(
        crash(),
        name=watcher.DCA_WORKER_TASK_NAME,
    )
    await asyncio.sleep(0)
    assert crashed_task.done()

    watcher._worker_tasks = [crashed_task]
    watcher._ensure_worker_tasks()

    replacement = watcher._worker_tasks[0]
    assert replacement is not crashed_task
    assert replacement.get_name() == watcher.DCA_WORKER_TASK_NAME
    assert not replacement.done()

    watcher.status = False
    replacement.cancel()
    await asyncio.gather(replacement, return_exceptions=True)


@pytest.mark.asyncio
async def test_watcher_reload_coalesces_rapid_config_changes(monkeypatch) -> None:
    watcher = Watcher()
    events: list[str] = []
    old_close_started = asyncio.Event()
    old_close_release = asyncio.Event()
    created_exchanges: list[object] = []

    class ExistingExchange:
        async def close(self) -> None:
            events.append("old_close_start")
            old_close_started.set()
            await old_close_release.wait()
            events.append("old_close_end")

    class FakeExchange:
        def __init__(self, params: dict) -> None:
            self.params = params
            self.closed = False
            created_exchanges.append(self)

        def set_sandbox_mode(self, _enabled: bool) -> None:
            return None

        async def close(self) -> None:
            self.closed = True
            events.append(self.params["options"]["defaultType"])

    monkeypatch.setattr(watcher_module.ccxtpro, "binance", FakeExchange)

    watcher.exchange = ExistingExchange()

    watcher.on_config_change(
        {
            "exchange": "binance",
            "market": "spot",
            "dry_run": False,
            "sandbox": False,
        }
    )
    await asyncio.wait_for(old_close_started.wait(), timeout=1)

    first_reload_task = watcher._reload_task
    watcher.on_config_change(
        {
            "exchange": "binance",
            "market": "future",
            "dry_run": False,
            "sandbox": False,
        }
    )

    assert watcher._reload_task is first_reload_task

    old_close_release.set()
    await asyncio.wait_for(watcher._reload_task, timeout=1)

    assert len(created_exchanges) == 2
    assert created_exchanges[0].closed is True
    assert created_exchanges[1].closed is False
    assert created_exchanges[1].params["options"]["defaultType"] == "future"


@pytest.mark.asyncio
async def test_watcher_reload_ignores_sandbox_in_dry_run(monkeypatch) -> None:
    watcher = Watcher()
    calls: list[str] = []

    class FakeExchange:
        def __init__(self, _params: dict) -> None:
            return None

        def enableDemoTrading(self, enabled: bool) -> None:
            if enabled:
                calls.append("demo")

        def set_sandbox_mode(self, enabled: bool) -> None:
            if enabled:
                calls.append("sandbox")

    monkeypatch.setattr(watcher_module.ccxtpro, "binance", FakeExchange)

    await watcher._reload_exchange_client(
        {
            "exchange": "binance",
            "market": "spot",
            "dry_run": True,
            "sandbox": True,
        }
    )

    assert calls == ["demo"]
