"""Bounded lifecycle-owned queue for optional AI background work."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import helper

logging = helper.LoggerFactory.get_logger("logs/ai_trust.log", "ai_work_queue")
WorkFactory = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class AiWorkItem:
    """One deduplicated queued AI operation."""

    key: str
    factory: WorkFactory
    enqueued_at: float


class AiWorkQueue:
    """Run bounded AI work without detached fire-and-forget tasks."""

    def __init__(self, *, capacity: int = 256, worker_count: int = 2) -> None:
        self._queue: asyncio.Queue[AiWorkItem] = asyncio.Queue(maxsize=capacity)
        self._worker_count = worker_count
        self._workers: list[asyncio.Task[Any]] = []
        self._pending_keys: set[str] = set()
        self._accepting = False
        self._coalesced_count = 0
        self._rejected_count = 0
        self._last_error: str | None = None

    async def start(self, task_group: asyncio.TaskGroup) -> None:
        """Start workers owned by the application TaskGroup."""
        if self._accepting:
            return
        self._accepting = True
        self._workers = [
            task_group.create_task(
                self._worker(index),
                name=f"moonwalker:ai-worker-{index}",
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
        """Queue work, coalescing duplicates and optionally applying backpressure."""
        normalized_key = str(key).strip()
        if not self._accepting or not normalized_key:
            self._rejected_count += 1
            return False
        if normalized_key in self._pending_keys:
            self._coalesced_count += 1
            return False

        item = AiWorkItem(
            key=normalized_key,
            factory=factory,
            enqueued_at=time.monotonic(),
        )
        self._pending_keys.add(normalized_key)
        if backpressure:
            try:
                await self._queue.put(item)
            except BaseException:
                self._pending_keys.discard(normalized_key)
                raise
            return True
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._pending_keys.discard(normalized_key)
            self._rejected_count += 1
            return False
        return True

    async def _worker(self, _index: int) -> None:
        """Consume queue items until lifespan cancellation."""
        while True:
            item = await self._queue.get()
            try:
                await item.factory()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - isolate optional AI work.
                self._last_error = f"{type(exc).__name__}: {exc}"
                logging.error(
                    "AI background work failed for %s: %s",
                    item.key,
                    exc,
                    exc_info=True,
                )
            finally:
                self._pending_keys.discard(item.key)
                self._queue.task_done()

    async def stop(self, *, drain_timeout: float = 5.0) -> None:
        """Stop accepting work, drain to a deadline, then cancel workers."""
        self._accepting = False
        try:
            await asyncio.wait_for(self._queue.join(), timeout=drain_timeout)
        except TimeoutError:
            logging.warning(
                "AI work queue drain timed out with %s item(s) pending.",
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
        queued_items = list(self._queue._queue)
        if queued_items:
            oldest_age_seconds = max(
                0.0,
                time.monotonic() - queued_items[0].enqueued_at,
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


ai_work_queue = AiWorkQueue()
