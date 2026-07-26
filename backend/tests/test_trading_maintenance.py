"""Regression tests for restore/order mutual exclusion."""

from __future__ import annotations

import asyncio
import types
from typing import Any

import pytest
import service.dca as dca_module
import service.orders as orders_module
from service.dca import Dca
from service.orders import Orders
from service.trading_maintenance import TradingMaintenanceBarrier


@pytest.mark.asyncio
async def test_maintenance_waits_for_active_order_operation() -> None:
    """Destructive maintenance must start only after admitted work drains."""
    barrier = TradingMaintenanceBarrier()
    operation_started = asyncio.Event()
    release_operation = asyncio.Event()
    maintenance_started = asyncio.Event()

    async def run_operation() -> None:
        async with barrier.operation() as admitted:
            assert admitted is True
            operation_started.set()
            await release_operation.wait()

    async def run_maintenance() -> None:
        async with barrier.maintenance():
            maintenance_started.set()

    operation_task = asyncio.create_task(run_operation())
    await operation_started.wait()
    maintenance_task = asyncio.create_task(run_maintenance())
    await asyncio.sleep(0)

    assert maintenance_started.is_set() is False
    release_operation.set()
    await operation_task
    await maintenance_task
    assert maintenance_started.is_set() is True


@pytest.mark.asyncio
async def test_sell_is_rejected_while_restore_owns_maintenance_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale DCA sell snapshot must not reach the exchange during restore."""
    barrier = TradingMaintenanceBarrier()
    monkeypatch.setattr(orders_module, "trading_maintenance_barrier", barrier)
    exchange_called = False

    async def create_spot_sell(
        _order: dict[str, Any],
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        nonlocal exchange_called
        exchange_called = True
        return {}

    orders = Orders()
    orders.exchange = types.SimpleNamespace(
        create_spot_sell=create_spot_sell,
        close=types.SimpleNamespace(),
    )

    async with barrier.maintenance():
        await orders.receive_sell_order({"symbol": "BTC/USDT"}, {})

    assert exchange_called is False


@pytest.mark.asyncio
async def test_maintenance_drains_complete_dca_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ticker snapshot cannot survive across restore and sell restored state."""
    barrier = TradingMaintenanceBarrier()
    monkeypatch.setattr(dca_module, "trading_maintenance_barrier", barrier)
    monkeypatch.setattr(orders_module, "trading_maintenance_barrier", barrier)
    evaluation_started = asyncio.Event()
    release_evaluation = asyncio.Event()
    maintenance_started = asyncio.Event()

    async def get_trades_for_orders(_symbol: str) -> None:
        evaluation_started.set()
        await release_evaluation.wait()
        return None

    dca = Dca()
    dca.trades = types.SimpleNamespace(
        get_trades_for_orders=get_trades_for_orders,
    )

    ticker_task = asyncio.create_task(
        dca.process_ticker_data(
            {
                "type": "ticker_price",
                "ticker": {"symbol": "BTC/USDT", "price": 100.0},
            },
            {},
        )
    )
    await evaluation_started.wait()

    async def run_maintenance() -> None:
        async with barrier.maintenance():
            maintenance_started.set()

    maintenance_task = asyncio.create_task(run_maintenance())
    await asyncio.sleep(0)
    assert maintenance_started.is_set() is False

    release_evaluation.set()
    await ticker_task
    await maintenance_task
    assert maintenance_started.is_set() is True
