"""Coalesced runtime change notifications for read-only dashboard streams."""

import asyncio
from collections.abc import AsyncGenerator

from service.websocket_fanout import CurrentStateProjection


class AccumulationStatusEvents:
    """Wake each dashboard once per changed snapshot, without polling tasks."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[bool]] = set()
        self._closed = False
        self.projections = CurrentStateProjection()

    def publish(self) -> None:
        """Coalesce a burst of changes to the latest snapshot for slow clients."""
        self.projections.invalidate()
        if not self._closed:
            for queue in self._queues:
                if not queue.full():
                    queue.put_nowait(True)

    @property
    def connected(self) -> bool:
        """Avoid dashboard projection work when no dashboard is subscribed."""
        return bool(self._queues) and not self._closed

    def close(self) -> None:
        """End subscriptions when their lifespan owner stops."""
        self._closed = True
        self.projections.invalidate()
        for queue in self._queues:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(False)

    async def subscribe(self) -> AsyncGenerator[None, None]:
        """Yield immediately on connect, then only after a runtime change."""
        if self._closed:
            return
        if not self._queues:
            self.projections.invalidate()
        queue: asyncio.Queue[bool] = asyncio.Queue(maxsize=1)
        self._queues.add(queue)
        try:
            yield None
            while await queue.get():
                yield None
        finally:
            self._queues.discard(queue)
            if not self._queues:
                self.projections.invalidate()
