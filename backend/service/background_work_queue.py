"""Reusable bounded work queue owned by the application lifespan."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

WorkFactory = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class BackgroundWorkItem:
    """One deduplicated background operation."""

    key: str
    factory: WorkFactory
    enqueued_at: float


class BoundedWorkQueue:
    """Run deduplicated work in bounded lifespan-owned workers."""

    def __init__(
        self,
        *,
        name: str,
        task_prefix: str,
        logger: Any,
        capacity: int,
        worker_count: int,
    ) -> None:
        self._name = name
        self._task_prefix = task_prefix
        self._logger = logger
        self._queue: asyncio.Queue[BackgroundWorkItem] = asyncio.Queue(maxsize=capacity)
        self._worker_count = worker_count
        self._workers: list[asyncio.Task[Any]] = []
        self._pending_keys: set[str] = set()
        self._enqueued_at_by_key: dict[str, float] = {}
        self._accepting = False
        self._coalesced_count = 0
        self._rejected_count = 0
        self._last_error: str | None = None

    async def start(self, task_group: asyncio.TaskGroup) -> None:
        """Start workers supervised by the application TaskGroup."""
        if self._accepting:
            return
        self._accepting = True
        self._workers = [
            task_group.create_task(
                self._worker(index),
                name=f"moonwalker:{self._task_prefix}-worker-{index}",
            )
            for index in range(self._worker_count)
        ]

    async def submit(
        self,
        key: str,
        factory: WorkFactory,
        *,
        backpressure: bool,
    ) -> bool:
        """Queue work, coalescing duplicates and applying bounded admission."""
        normalized_key = str(key).strip()
        if not self._accepting or not normalized_key:
            self._rejected_count += 1
            return False
        if normalized_key in self._pending_keys:
            self._coalesced_count += 1
            return False

        enqueued_at = time.monotonic()
        item = BackgroundWorkItem(
            key=normalized_key,
            factory=factory,
            enqueued_at=enqueued_at,
        )
        self._pending_keys.add(normalized_key)
        self._enqueued_at_by_key[normalized_key] = enqueued_at
        if backpressure:
            try:
                await self._queue.put(item)
            except BaseException:
                self._forget(normalized_key)
                raise
            return True
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._forget(normalized_key)
            self._rejected_count += 1
            self._logger.warning(
                "%s queue is full; rejected background work %s.",
                self._name,
                normalized_key,
            )
            return False
        return True

    async def submit_or_run_inline(
        self,
        key: str,
        factory: WorkFactory,
    ) -> bool:
        """Queue during runtime, or run inline for direct scripts and tests."""
        if not self._accepting:
            await factory()
            return True
        return await self.submit(key, factory, backpressure=False)

    async def _worker(self, _index: int) -> None:
        """Consume items until lifespan cancellation."""
        while True:
            item = await self._queue.get()
            try:
                await item.factory()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - isolate optional work.
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._logger.error(
                    "%s failed for %s: %s",
                    self._name,
                    item.key,
                    exc,
                    exc_info=True,
                )
            finally:
                self._forget(item.key)
                self._queue.task_done()

    async def stop(self, *, drain_timeout: float = 5.0) -> None:
        """Stop admission, drain to a deadline, then cancel workers."""
        self._accepting = False
        try:
            await asyncio.wait_for(self._queue.join(), timeout=drain_timeout)
        except TimeoutError:
            self._logger.warning(
                "%s queue drain timed out with %s item(s) pending.",
                self._name,
                len(self._pending_keys),
            )
        finally:
            for worker in self._workers:
                worker.cancel()
            if self._workers:
                await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()

    def status(self) -> dict[str, Any]:
        """Return bounded operational queue metrics."""
        oldest_age_seconds = 0.0
        if self._enqueued_at_by_key:
            oldest_age_seconds = max(
                0.0,
                time.monotonic() - min(self._enqueued_at_by_key.values()),
            )
        return {
            "depth": self._queue.qsize(),
            "pending_count": len(self._pending_keys),
            "oldest_age_seconds": round(oldest_age_seconds, 3),
            "rejected_count": self._rejected_count,
            "coalesced_count": self._coalesced_count,
            "last_error": self._last_error,
            "accepting": self._accepting,
        }

    def _forget(self, key: str) -> None:
        """Remove one completed or rejected work identity."""
        self._pending_keys.discard(key)
        self._enqueued_at_by_key.pop(key, None)
