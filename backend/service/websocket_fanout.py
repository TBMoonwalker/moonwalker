"""Shared fan-out helper for periodic WebSocket payload streaming."""

import asyncio
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
    ) -> None:
        self._name = name
        self._interval_seconds = interval_seconds
        self._producer = producer
        self._logger = logger
        self._task: asyncio.Task[None] | None = None
        self._subscribers: set[asyncio.Queue[str | object]] = set()
        self._latest_payload: str | None = None
        self._has_subscribers = asyncio.Event()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the internal producer task if it is not already running."""
        running_loop = asyncio.get_running_loop()
        async with self._lock:
            if self._task is not None and self._task.get_loop() is not running_loop:
                self._task = None
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(
                    self._run(), name=f"ws-fanout:{self._name}"
                )

    async def stop(self) -> None:
        """Stop the internal producer task and notify subscribers to exit."""
        task: asyncio.Task[None] | None = None
        subscribers: tuple[asyncio.Queue[str | object], ...] = ()

        async with self._lock:
            task = self._task
            self._task = None
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()
            self._latest_payload = None
            self._has_subscribers.clear()

        for subscriber in subscribers:
            self._queue_signal(subscriber, _STOP)

        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def subscribe(self) -> AsyncGenerator[str, None]:
        """Subscribe to fan-out updates as an async generator."""
        await self.start()
        queue: asyncio.Queue[str | object] = asyncio.Queue(maxsize=1)
        latest_payload: str | None

        async with self._lock:
            self._subscribers.add(queue)
            self._has_subscribers.set()
            latest_payload = self._latest_payload

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
                if not self._subscribers:
                    self._latest_payload = None
                    self._has_subscribers.clear()

    async def _run(self) -> None:
        """Run producer loop and broadcast payloads while service is active."""
        while True:
            try:
                await self._has_subscribers.wait()
                payload = await self._producer()
                await self._broadcast(payload)
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

    async def _broadcast(self, payload: str) -> None:
        """Broadcast payload to current subscribers."""
        subscribers: tuple[asyncio.Queue[str | object], ...]
        async with self._lock:
            self._latest_payload = payload
            subscribers = tuple(self._subscribers)

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
