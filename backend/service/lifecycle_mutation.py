"""Coordinate every trade-lifecycle mutation by symbol."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar

from service.order_requests import normalize_order_symbol
from service.trading_maintenance import (
    TradingMaintenanceBarrier,
    trading_maintenance_barrier,
)


class LifecycleMutationCoordinator:
    """Own maintenance admission and the sole per-symbol mutation lock."""

    def __init__(
        self,
        barrier: TradingMaintenanceBarrier = trading_maintenance_barrier,
    ) -> None:
        self._barrier = barrier
        self._locks: dict[str, asyncio.Lock] = {}
        self._held_symbols: ContextVar[frozenset[str]] = ContextVar(
            "moonwalker_held_lifecycle_symbols",
            default=frozenset(),
        )

    def assert_prelocked(self, symbol: str) -> str:
        """Validate that the current task owns the symbol mutation boundary."""
        normalized = normalize_order_symbol(symbol)
        if normalized not in self._held_symbols.get():
            raise RuntimeError(
                f"Lifecycle mutation for {normalized} requires the coordinator lock."
            )
        return normalized

    def _lock_for(self, symbol: str) -> asyncio.Lock:
        """Return the process-wide lock owned by this coordinator."""
        lock = self._locks.get(symbol)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[symbol] = lock
        return lock

    @asynccontextmanager
    async def prelocked(self, symbol: str) -> AsyncIterator[None]:
        """Expose an explicit no-reacquire boundary for internal operations."""
        self.assert_prelocked(symbol)
        yield

    @asynccontextmanager
    async def mutation(self, symbol: str) -> AsyncIterator[bool]:
        """Admit and serialize one symbol mutation without allowing re-entry."""
        normalized = normalize_order_symbol(symbol)
        held_symbols = self._held_symbols.get()
        if normalized in held_symbols:
            raise RuntimeError(
                f"Nested public lifecycle mutation for {normalized} is not allowed."
            )

        async with self._barrier.operation() as admitted:
            if not admitted:
                yield False
                return

            async with self._lock_for(normalized):
                token = self._held_symbols.set(held_symbols | {normalized})
                try:
                    yield True
                finally:
                    self._held_symbols.reset(token)


lifecycle_mutation_coordinator = LifecycleMutationCoordinator()
