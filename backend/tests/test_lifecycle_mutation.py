"""Tests for the sole trade-lifecycle mutation lock owner."""

from __future__ import annotations

import asyncio

import pytest
from service.lifecycle_mutation import LifecycleMutationCoordinator
from service.trading_maintenance import TradingMaintenanceBarrier


@pytest.mark.asyncio
async def test_same_symbol_mutations_are_serialized() -> None:
    coordinator = LifecycleMutationCoordinator(TradingMaintenanceBarrier())
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    events: list[str] = []

    async def first() -> None:
        async with coordinator.mutation("btc-usdc") as admitted:
            assert admitted is True
            events.append("first-enter")
            first_entered.set()
            await release_first.wait()
            events.append("first-exit")

    async def second() -> None:
        await first_entered.wait()
        async with coordinator.mutation("BTC/USDC") as admitted:
            assert admitted is True
            events.append("second-enter")

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_entered.wait()
    await asyncio.sleep(0)
    assert events == ["first-enter"]
    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert events == ["first-enter", "first-exit", "second-enter"]


@pytest.mark.asyncio
async def test_nested_public_mutation_fails_instead_of_deadlocking() -> None:
    coordinator = LifecycleMutationCoordinator(TradingMaintenanceBarrier())

    async with coordinator.mutation("ETH/USDC"):
        with pytest.raises(RuntimeError, match="Nested public lifecycle mutation"):
            async with asyncio.timeout(0.1):
                async with coordinator.mutation("eth-usdc"):
                    pass


@pytest.mark.asyncio
async def test_prelocked_contract_is_explicit() -> None:
    coordinator = LifecycleMutationCoordinator(TradingMaintenanceBarrier())

    with pytest.raises(RuntimeError, match="requires the coordinator lock"):
        coordinator.assert_prelocked("SOL/USDC")

    async with coordinator.mutation("SOL/USDC"):
        assert coordinator.assert_prelocked("sol-usdc") == "SOL/USDC"


@pytest.mark.asyncio
async def test_maintenance_rejects_new_symbol_mutations() -> None:
    barrier = TradingMaintenanceBarrier()
    coordinator = LifecycleMutationCoordinator(barrier)

    async with barrier.maintenance():
        async with coordinator.mutation("LINK/USDC") as admitted:
            assert admitted is False
