"""Shared fan-out helper for periodic WebSocket payload streaming."""

import asyncio
from collections import OrderedDict
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, cast

_STOP = object()


class WebSocketFanout:
    """Broadcast periodic producer output to all connected subscribers.

    The producer is executed once per interval and the latest payload is fanned out
    to all active subscribers. New subscribers receive the latest payload
    immediately when available.
    """

    def __init__(
        self,
        *,
        name: str,
        interval_seconds: float,
        producer: Callable[[], Awaitable[str]],
        logger: Any,
        fresh_producer: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._name = name
        self._interval_seconds = interval_seconds
        self._producer = producer
        self._fresh_producer = fresh_producer or producer
        self._logger = logger
        self._task: asyncio.Task[None] | None = None
        self._regular_task: asyncio.Task[None] | None = None
        self._fresh_task: asyncio.Task[None] | None = None
        self._subscribers: set[asyncio.Queue[str | object]] = set()
        self._fresh_after: dict[asyncio.Queue[str | object], int] = {}
        self._production_generation = 0
        self._latest_payload: str | None = None
        self._has_subscribers = asyncio.Event()
        self._lock = asyncio.Lock()
        self._stopped = False

    async def start(self) -> None:
        """Start the internal producer task if it is not already running."""
        async with self._lock:
            self._stopped = False
            self._ensure_task()

    def _ensure_task(self) -> None:
        """Start a producer under the lock after subscription admission."""
        running_loop = asyncio.get_running_loop()
        if self._task is not None and self._task.get_loop() is not running_loop:
            self._task = None
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run(), name=f"ws-fanout:{self._name}"
            )

    async def stop(self) -> None:
        """Stop the internal producer task and notify subscribers to exit."""
        task: asyncio.Task[None] | None = None
        fresh_task: asyncio.Task[None] | None = None
        regular_task: asyncio.Task[None] | None = None
        subscribers: tuple[asyncio.Queue[str | object], ...] = ()

        async with self._lock:
            self._stopped = True
            task = self._task
            self._task = None
            fresh_task = self._fresh_task
            self._fresh_task = None
            regular_task = self._regular_task
            self._regular_task = None
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()
            self._fresh_after.clear()
            self._latest_payload = None
            self._has_subscribers.clear()

        for subscriber in subscribers:
            self._queue_signal(subscriber, _STOP)

        if task is not None:
            task.cancel()
        if fresh_task is not None:
            fresh_task.cancel()
        if regular_task is not None:
            regular_task.cancel()
        await asyncio.gather(
            *(
                pending
                for pending in (task, fresh_task, regular_task)
                if pending is not None
            ),
            return_exceptions=True,
        )

    async def subscribe(
        self, *, require_new_production: bool = False
    ) -> AsyncGenerator[str, None]:
        """Subscribe, optionally waiting for production started after admission.

        Recovery subscribers continue receiving only the fresh producer's
        output so an older cached result cannot overwrite a refreshed value.
        This ordering does not establish the freshness of a producer's own
        caches or sources; callers must enforce those guarantees separately.
        Fresh producers must also be cancellation-safe, including database
        transaction entry and cleanup when the last subscriber disconnects.
        """
        queue: asyncio.Queue[str | object] = asyncio.Queue(maxsize=1)
        latest_payload: str | None

        async with self._lock:
            # A late socket must not resurrect producers after lifespan cleanup
            # has closed the database. Only an explicit start opens a new lifespan.
            if self._stopped:
                return
            self._ensure_task()
            self._subscribers.add(queue)
            if require_new_production:
                self._fresh_after[queue] = self._production_generation + 1
            self._has_subscribers.set()
            latest_payload = None if require_new_production else self._latest_payload

        if latest_payload is not None:
            self._queue_signal(queue, latest_payload)

        try:
            while True:
                payload = await queue.get()
                if payload is _STOP:
                    return
                yield cast(str, payload)
        finally:
            async with self._lock:
                self._subscribers.discard(queue)
                self._fresh_after.pop(queue, None)
                if not self._fresh_after and self._fresh_task is not None:
                    self._fresh_task.cancel()
                if (
                    not any(
                        subscriber not in self._fresh_after
                        for subscriber in self._subscribers
                    )
                    and self._regular_task is not None
                ):
                    self._regular_task.cancel()
                if not self._subscribers:
                    self._latest_payload = None
                    self._has_subscribers.clear()

    async def _run(self) -> None:
        """Run producer loop and broadcast payloads while service is active."""
        while True:
            try:
                await self._has_subscribers.wait()
                async with self._lock:
                    self._production_generation += 1
                    generation = self._production_generation
                    needs_fresh = any(
                        generation >= minimum for minimum in self._fresh_after.values()
                    )
                    if needs_fresh and (
                        self._fresh_task is None or self._fresh_task.done()
                    ):
                        self._fresh_task = asyncio.create_task(
                            self._produce_fresh(generation),
                            name=f"ws-fresh:{self._name}",
                        )
                    needs_regular = any(
                        subscriber not in self._fresh_after
                        for subscriber in self._subscribers
                    )
                    if needs_regular and (
                        self._regular_task is None or self._regular_task.done()
                    ):
                        self._regular_task = asyncio.create_task(
                            self._produce_regular(generation),
                            name=f"ws-regular:{self._name}",
                        )
                await asyncio.sleep(self._interval_seconds)
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001 - Keep broadcaster resilient.
                self._logger.error(
                    "Error in %s WebSocket fan-out producer: %s",
                    self._name,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(self._interval_seconds)

    async def _produce_regular(self, generation: int) -> None:
        """Produce ordinary snapshots without blocking recovery scheduling."""
        try:
            payload = await self._producer()
            await self._broadcast(payload, generation, fresh=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Retry on the next interval.
            self._logger.error(
                "Error in %s WebSocket producer: %s", self._name, exc, exc_info=True
            )

    async def _produce_fresh(self, generation: int) -> None:
        """Refresh recovery subscribers without stalling ordinary clients."""
        try:
            payload = await self._fresh_producer()
            await self._broadcast(payload, generation, fresh=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Retry on the next interval.
            self._logger.error(
                "Error in %s fresh WebSocket producer: %s",
                self._name,
                exc,
                exc_info=True,
            )

    async def _broadcast(self, payload: str, generation: int, *, fresh: bool) -> None:
        """Broadcast payload to current subscribers."""
        subscribers: tuple[asyncio.Queue[str | object], ...]
        async with self._lock:
            if not fresh:
                self._latest_payload = payload
            subscribers = tuple(
                subscriber
                for subscriber in self._subscribers
                if (
                    subscriber in self._fresh_after
                    and fresh
                    and generation >= self._fresh_after[subscriber]
                )
                or (subscriber not in self._fresh_after and not fresh)
            )

        for subscriber in subscribers:
            self._queue_signal(subscriber, payload)

    @staticmethod
    def _queue_signal(
        queue: asyncio.Queue[str | object], payload: str | object
    ) -> None:
        """Queue payload while keeping only the latest message per subscriber."""
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(payload)


class CurrentStateProjection:
    """Share event-driven read-only payloads without starting a producer task.

    The lifespan owner invalidates on state changes and after its last client
    leaves. The caller owns DB context and cancellation completion. Entries are
    bounded independently of the number of distinct dashboard selections.
    """

    def __init__(self) -> None:
        self._generation = 0
        self._payloads: OrderedDict[object, str] = OrderedDict()
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        """Forget payloads without disrupting a read already in progress."""
        self._generation += 1
        self._payloads.clear()

    async def read(self, key: object, producer: Callable[[], Awaitable[str]]) -> str:
        """Build a matching selection once per state generation."""
        async with self._lock:
            if key in self._payloads:
                self._payloads.move_to_end(key)
                return self._payloads[key]
            generation = self._generation
            payload = await producer()
            if generation == self._generation:
                self._payloads[key] = payload
                if len(self._payloads) > 128:
                    self._payloads.popitem(last=False)
            return payload
