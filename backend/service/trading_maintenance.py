"""Coordinate destructive maintenance with exchange-order execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar


class TradingMaintenanceBarrier:
    """Drain active order work and reject new work during maintenance."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active_operations = 0
        self._maintenance_active = False
        self._operation_depth: ContextVar[int] = ContextVar(
            "moonwalker_trading_operation_depth",
            default=0,
        )

    @property
    def maintenance_active(self) -> bool:
        """Return whether destructive maintenance currently owns the barrier."""
        return self._maintenance_active

    @asynccontextmanager
    async def operation(self) -> AsyncIterator[bool]:
        """Admit one order operation unless maintenance has already started."""
        depth = self._operation_depth.get()
        if depth > 0:
            token = self._operation_depth.set(depth + 1)
            try:
                yield True
            finally:
                self._operation_depth.reset(token)
            return

        async with self._condition:
            if self._maintenance_active:
                yield False
                return
            self._active_operations += 1

        token = self._operation_depth.set(1)
        try:
            yield True
        finally:
            self._operation_depth.reset(token)
            async with self._condition:
                self._active_operations -= 1
                if self._active_operations == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def maintenance(self) -> AsyncIterator[None]:
        """Reject new order work and wait for admitted work to finish."""
        async with self._condition:
            if self._maintenance_active:
                raise RuntimeError("Trading maintenance is already active.")
            self._maintenance_active = True
            while self._active_operations:
                await self._condition.wait()

        try:
            yield
        finally:
            async with self._condition:
                self._maintenance_active = False
                self._condition.notify_all()


trading_maintenance_barrier = TradingMaintenanceBarrier()
