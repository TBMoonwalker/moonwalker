import asyncio

import pytest
from service.watcher import Watcher


def test_prepare_ohlcv_write_merges_same_timestamp() -> None:
    watcher = Watcher()
    symbol = "BTC/USDC"
    Watcher.candles = {}

    first = [1_000, 10.0, 10.0, 10.0, 10.0, 1.0]
    assert watcher._Watcher__prepare_ohlcv_write(symbol, [first]) is None

    second = [1_000, 11.0, 12.0, 9.0, 11.0, 0.5]
    assert watcher._Watcher__prepare_ohlcv_write(symbol, [second]) is None

    assert Watcher.candles[symbol] == [1000.0, 10.0, 12.0, 9.0, 11.0, 1.5]


def test_prepare_ohlcv_write_returns_merged_payload_on_rollover() -> None:
    watcher = Watcher()
    symbol = "BTC/USDC"
    Watcher.candles = {}

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
    assert Watcher.candles[symbol] == next_candle


@pytest.mark.asyncio
async def test_dca_worker_survives_unexpected_processing_exception() -> None:
    watcher = Watcher()
    watcher.config = {}
    calls: list[float] = []

    async def fake_process_ticker_data(ticker_price: dict, config: dict) -> None:
        calls.append(float(ticker_price["ticker"]["price"]))
        if len(calls) == 1:
            raise KeyError("unexpected")
        watcher.status = False

    watcher.dca.process_ticker_data = fake_process_ticker_data
    worker = asyncio.create_task(watcher._process_dca_queue())

    await watcher.dca_queue.put(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 1.0}}
    )
    await watcher.dca_queue.put(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDC", "price": 2.0}}
    )

    await asyncio.wait_for(worker, timeout=2)

    assert calls == [1.0, 2.0]
    assert watcher.dca_queue.qsize() == 0


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
