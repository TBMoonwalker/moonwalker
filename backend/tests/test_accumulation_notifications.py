"""Input hints wake only the lifespan owner, without becoming execution evidence."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from service.accumulation.notifications import AccumulationInputNotifications
from service.accumulation.runtime import AccumulationRuntime
from service.exchange_balance_manager import ExchangeBalanceManager
from service.watcher import Watcher


def test_single_owner_disconnect_and_observer_failure_are_safe(caplog, monkeypatch):
    import logging

    monkeypatch.setattr(logging.getLogger("accumulation"), "propagate", True)
    caplog.set_level(logging.INFO, logger="accumulation")

    notifications = AccumulationInputNotifications()
    first, second = object(), object()
    listener = Mock()
    notifications.publish("BTC/USDC")
    notifications.attach(first, listener)
    with pytest.raises(RuntimeError, match="subscriber"):
        notifications.attach(second, Mock())
    notifications.publish("BTC/USDC")
    listener.assert_called_once_with("BTC/USDC")
    notifications.detach(first)
    notifications.attach(second, Mock(side_effect=RuntimeError("observer failed")))
    notifications.detach(first)
    assert notifications.connected
    notifications.publish()
    assert "Accumulation input notification failed" in caplog.text
    notifications.detach(second)
    assert not notifications.connected


@pytest.mark.asyncio
async def test_quote_and_wallet_producers_publish_only_change_hints(monkeypatch):
    notifications = AccumulationInputNotifications()
    hints = []
    notifications.attach(object(), hints.append)
    monkeypatch.setattr(
        "service.watcher.accumulation_input_notifications", notifications
    )
    monkeypatch.setattr(
        "service.exchange_balance_manager.accumulation_input_notifications",
        notifications,
    )
    watcher = Watcher.__new__(Watcher)
    watcher.last_price, watcher.event_queue = {}, asyncio.Queue()
    await watcher.push_event("BTC/USDC", 100, [])
    await watcher.push_event("BTC/USDC", 100, [])
    await watcher.push_event("BTC/USDC", 99, [])
    assert hints == ["BTC/USDC", "BTC/USDC"]
    balance = {
        "free": {"USDC": "10"},
        "used": {"USDC": "2"},
        "info": {"private": "never published"},
    }
    exchange = SimpleNamespace(fetch_balance=AsyncMock(return_value=balance))
    manager = ExchangeBalanceManager(
        logger=Mock(),
        balance_cache_ttl_seconds=60,
        get_exchange=lambda: exchange,
        resolve_symbol=lambda symbol: symbol,
    )
    await manager.get_balance_snapshot()
    await manager.get_balance_snapshot()
    assert hints[-1] is None and hints.count(None) == 1
    balance["info"] = {"changed": "ignored"}
    await manager.get_balance_snapshot(force_refresh=True)
    assert hints.count(None) == 1
    balance["free"]["USDC"] = "12"
    await manager.get_balance_snapshot(force_refresh=True)
    balance["used"]["USDC"] = "0"
    await manager.get_balance_snapshot(force_refresh=True)
    assert hints.count(None) == 3
    exchange.fetch_balance.side_effect = OSError("offline")
    manager.BALANCE_FETCH_ATTEMPTS = 1
    with pytest.raises(OSError):
        await manager.get_balance_snapshot(force_refresh=True)
    assert hints.count(None) == 3


def runtime_fixture():
    clock = [10000]
    adapter = SimpleNamespace(
        exchange=SimpleNamespace(),
        account_scope=AsyncMock(),
        readiness=AsyncMock(),
        clock_ms=lambda: clock[0],
    )
    runtime = AccumulationRuntime(adapter)
    runtime._started = True
    runtime._all_dirty = False
    runtime._input_symbols = {"BTC/USDC", "ETH/USDC"}
    return runtime, clock


def test_quote_bursts_remain_bounded_and_wallet_changes_mark_all_holdings():
    runtime, clock = runtime_fixture()
    runtime.notify_inputs("UNMANAGED/USDC")
    assert not runtime._wake.is_set() and not runtime._dirty
    runtime.notify_inputs("BTC/USDC")
    assert runtime._wake.is_set() and runtime._dirty == {"BTC/USDC"}
    runtime._wake.clear()
    for _ in range(1000):
        runtime.notify_inputs("ETH/USDC")
    assert not runtime._wake.is_set()
    assert runtime._dirty == {"BTC/USDC", "ETH/USDC"}
    runtime.notify_inputs()
    assert runtime._all_dirty and not runtime._dirty
    clock[0] += 5000
    runtime.notify_inputs("BTC/USDC")
    assert runtime._wake.is_set()
    runtime.request_stop()
    runtime._wake.clear()
    runtime.notify_inputs()
    assert not runtime._wake.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_worker_owns_subscription_and_cleans_up_on_cancel_or_failure(
    monkeypatch, failure
):
    notifications = AccumulationInputNotifications()
    monkeypatch.setattr(
        "service.accumulation.runtime.accumulation_input_notifications", notifications
    )
    runtime, _ = runtime_fixture()
    entered = asyncio.Event()

    async def tick():
        entered.set()
        if failure:
            raise RuntimeError("worker failed")

    runtime.tick = tick
    task = asyncio.create_task(runtime.run())
    await entered.wait()
    if failure:
        with pytest.raises(RuntimeError, match="worker failed"):
            await task
    else:
        assert notifications.connected
        notifications.publish("BTC/USDC")
        assert runtime._dirty == {"BTC/USDC"}
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not notifications.connected


@pytest.mark.asyncio
async def test_repair_only_session_never_attaches_an_input_listener(monkeypatch):
    notifications = AccumulationInputNotifications()
    monkeypatch.setattr(
        "service.accumulation.runtime.accumulation_input_notifications", notifications
    )
    runtime, _ = runtime_fixture()
    runtime._started, runtime._repair_only = False, True
    with pytest.raises(RuntimeError, match="not ready"):
        await runtime.run()
    assert not notifications.connected
