import asyncio
import types

import helper
import pytest
import service.watcher as watcher_module
import service.watcher_runtime as watcher_runtime
from service.watcher import Watcher


def test_normalize_symbols_flattens_and_deduplicates() -> None:
    result = watcher_runtime.normalize_symbols(
        ["BTC/USDC", ["ETH/USDC", "BTC/USDC"], "invalid", 1, "SOL/USDC"]
    )

    assert result == ["BTC/USDC", "ETH/USDC", "SOL/USDC"]


def test_get_mandatory_symbols_uses_currency_only_when_enabled() -> None:
    assert watcher_runtime.get_mandatory_symbols({"btc_pulse": False}) == set()
    assert watcher_runtime.get_mandatory_symbols(
        {"btc_pulse": True, "currency": "usdt"}
    ) == {"BTC/USDT"}


def test_compose_ticker_symbols_merges_sources_and_converts_when_ohlcv() -> None:
    utils = helper.Utils()

    result = watcher_runtime.compose_ticker_symbols(
        utils,
        base_symbols=["ETH/USDC"],
        signal_symbols={"BTC/USDC"},
        mandatory_symbols={"BTC/USDC", "SOL/USDC"},
        exchange_watcher_ohlcv=True,
        timeframe="1m",
    )

    assert result == [
        ["ETH/USDC", "1m"],
        ["BTC/USDC", "1m"],
        ["SOL/USDC", "1m"],
    ]


def test_prepare_ohlcv_write_rolls_closed_candle_forward() -> None:
    candles: dict[str, list[float]] = {}
    symbol = "BTC/USDC"

    assert (
        watcher_runtime.prepare_ohlcv_write(
            candles, symbol, [[1_000, 10, 10, 10, 10, 1]]
        )
        is None
    )
    assert (
        watcher_runtime.prepare_ohlcv_write(
            candles, symbol, [[1_000, 10, 12, 9, 11, 0.5]]
        )
        is None
    )

    payload = watcher_runtime.prepare_ohlcv_write(
        candles, symbol, [[2_000, 11, 13, 10, 12, 2]]
    )

    assert payload == {
        "timestamp": 1000.0,
        "symbol": symbol,
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 1.5,
    }
    assert candles[symbol] == [2_000, 11, 13, 10, 12, 2]


def test_refresh_symbol_targets_from_current_state_recomposes_and_notifies() -> None:
    watcher = Watcher()
    watcher.runtime_state.exchange_watcher_ohlcv = False
    watcher.runtime_state.signal_symbols = {"BTC/USDC"}
    watcher.runtime_state.mandatory_symbols = {"SOL/USDC"}
    watcher.runtime_state.ticker_symbols = [["ETH/USDC", "1m"]]

    ticker_symbols = watcher._refresh_symbol_targets_from_current_state()

    assert ticker_symbols == ["ETH/USDC", "BTC/USDC", "SOL/USDC"]
    assert watcher.runtime_state.ticker_symbols == [
        "ETH/USDC",
        "BTC/USDC",
        "SOL/USDC",
    ]
    assert watcher.runtime_state.symbol_update_event.is_set()


@pytest.mark.asyncio
async def test_refresh_symbol_targets_from_trades_updates_signal_symbols() -> None:
    watcher = Watcher()
    watcher.runtime_state.exchange_watcher_ohlcv = False

    async def fake_get_symbols() -> list[str]:
        return ["ETH/USDC"]

    watcher.trades.get_symbols = fake_get_symbols

    ticker_symbols = await watcher._refresh_symbol_targets_from_trades(
        signal_symbols=["BTC/USDC"]
    )

    assert watcher.runtime_state.signal_symbols == {"BTC/USDC"}
    assert ticker_symbols == ["ETH/USDC", "BTC/USDC"]
    assert watcher.runtime_state.ticker_symbols == ["ETH/USDC", "BTC/USDC"]
    assert watcher.runtime_state.symbol_update_event.is_set()


@pytest.mark.asyncio
async def test_shutdown_cleans_up_internal_tasks_and_is_idempotent() -> None:
    watcher = Watcher()
    close_calls: list[str] = []

    async def sleep_forever() -> None:
        await asyncio.sleep(3600)

    class FakeExchange:
        async def close(self) -> None:
            close_calls.append("closed")

    consumer_task = asyncio.create_task(sleep_forever(), name="watcher:event_consumer")
    worker_task = asyncio.create_task(
        sleep_forever(), name=watcher.DCA_WORKER_TASK_NAME
    )
    symbol_task = asyncio.create_task(sleep_forever(), name="watch:BTC/USDC")
    reload_task = asyncio.create_task(sleep_forever(), name="watcher:reload")
    btc_warmup_task = asyncio.create_task(sleep_forever(), name="watcher:btc_warmup")

    watcher._consumer_task = consumer_task
    watcher._worker_tasks = [worker_task]
    watcher.symbol_tasks = {"BTC/USDC": symbol_task}
    watcher._reload_task = reload_task
    watcher._btc_warmup_task = btc_warmup_task
    watcher.exchange = FakeExchange()

    await watcher.shutdown()
    await watcher.shutdown()

    assert close_calls == ["closed"]
    assert watcher._consumer_task is None
    assert watcher._worker_tasks == []
    assert watcher.symbol_tasks == {}
    assert watcher._reload_task is None
    assert watcher._btc_warmup_task is None
    assert watcher.exchange is None
    assert consumer_task.cancelled()
    assert worker_task.cancelled()
    assert symbol_task.cancelled()
    assert reload_task.cancelled()
    assert btc_warmup_task.cancelled()


@pytest.mark.asyncio
async def test_watch_tickers_cancellation_uses_shared_cleanup() -> None:
    watcher = Watcher()
    close_calls: list[str] = []

    class FakeExchange:
        async def close(self) -> None:
            close_calls.append("closed")

    async def fake_await_btc_warmup_if_needed(self) -> None:
        return None

    async def fake_refresh_symbol_targets_from_trades(
        self,
        *,
        signal_symbols=None,
        notify: bool = True,
    ) -> list[str]:
        return []

    async def fake_sync_symbol_tasks(self) -> None:
        return None

    async def fake_wait_for_updates(self) -> None:
        await asyncio.sleep(3600)

    async def fake_process_events(self) -> None:
        await asyncio.sleep(3600)

    async def fake_worker() -> None:
        await asyncio.sleep(3600)

    def fake_create_worker_task(self, task_name: str):
        return asyncio.create_task(fake_worker(), name=task_name)

    watcher.exchange = FakeExchange()
    watcher._await_btc_warmup_if_needed = types.MethodType(
        fake_await_btc_warmup_if_needed, watcher
    )
    watcher._refresh_symbol_targets_from_trades = types.MethodType(
        fake_refresh_symbol_targets_from_trades, watcher
    )
    watcher._Watcher__sync_symbol_tasks = types.MethodType(
        fake_sync_symbol_tasks, watcher
    )
    watcher._Watcher__wait_for_updates = types.MethodType(
        fake_wait_for_updates, watcher
    )
    watcher.process_events = types.MethodType(fake_process_events, watcher)
    watcher._create_worker_task = types.MethodType(fake_create_worker_task, watcher)

    task = asyncio.create_task(watcher.watch_tickers())
    await asyncio.sleep(0)
    task.cancel()

    result = await asyncio.gather(task, return_exceptions=True)

    assert isinstance(result[0], asyncio.CancelledError)
    assert close_calls == ["closed"]
    assert watcher._consumer_task is None
    assert watcher._worker_tasks == []
    assert watcher.symbol_tasks == {}
    assert watcher.exchange is None


@pytest.mark.asyncio
async def test_watch_symbol_processes_one_ohlcv_cycle() -> None:
    watcher = Watcher()
    watcher.runtime_state.exchange_watcher_ohlcv = True
    watcher.runtime_state.timeframe = "15m"

    class FakeExchange:
        async def watch_ohlcv(self, symbol: str, timeframe: str):
            assert symbol == "BTC/USDC"
            assert timeframe == "15m"
            return [[1_000, 10.0, 12.0, 9.0, 11.0, 1.5]]

    watcher.exchange = FakeExchange()

    await watcher.watch_symbol("BTC/USDC")

    event = await asyncio.wait_for(watcher.event_queue.get(), timeout=1)
    assert event == {
        "symbol": "BTC/USDC",
        "price": 11.0,
        "ohlcv": [[1_000, 10.0, 12.0, 9.0, 11.0, 1.5]],
    }


@pytest.mark.asyncio
async def test_watch_symbol_processes_one_trade_cycle() -> None:
    watcher = Watcher()
    watcher.runtime_state.exchange_watcher_ohlcv = False
    watcher.runtime_state.timeframe = "1h"

    class FakeExchange:
        async def watch_trades(self, symbol: str):
            assert symbol == "ETH/USDC"
            return [{"price": 12.5}]

        def build_ohlcvc(self, trades: list[dict[str, float]], timeframe: str):
            assert timeframe == "1h"
            return [[2_000, 12.5, 12.5, 12.5, 12.5, 1.0]]

    watcher.exchange = FakeExchange()

    await watcher.watch_symbol("ETH/USDC")

    event = await asyncio.wait_for(watcher.event_queue.get(), timeout=1)
    assert event == {
        "symbol": "ETH/USDC",
        "price": 12.5,
        "ohlcv": [[2_000, 12.5, 12.5, 12.5, 12.5, 1.0]],
    }


@pytest.mark.asyncio
async def test_watch_symbol_with_reconnect_uses_shared_backoff(monkeypatch) -> None:
    watcher = Watcher()
    attempts: list[str] = []
    sleep_calls: list[int] = []

    monkeypatch.setattr(Watcher, "RECONNECT_DELAY", 1)
    monkeypatch.setattr(Watcher, "MAX_RECONNECT_DELAY", 2)

    async def fake_sleep(delay: int) -> None:
        sleep_calls.append(delay)

    async def fake_watch_symbol(symbol: str) -> None:
        attempts.append(symbol)
        if len(attempts) < 3:
            raise watcher_module.ccxtpro.NetworkError("boom")
        watcher.status = False

    monkeypatch.setattr(watcher_module.asyncio, "sleep", fake_sleep)
    watcher.watch_symbol = fake_watch_symbol

    await watcher.watch_symbol_with_reconnect("BTC/USDC")

    assert attempts == ["BTC/USDC", "BTC/USDC", "BTC/USDC"]
    assert sleep_calls == [1, 2]
