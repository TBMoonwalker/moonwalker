"""Tests for bounded lifecycle-owned AI work."""

from __future__ import annotations

import asyncio

import pytest
from service.ai_work_queue import AiWorkQueue


@pytest.mark.asyncio
async def test_ai_work_queue_drains_and_coalesces_duplicate_keys() -> None:
    """One logical event should run once even when submitted repeatedly."""
    queue = AiWorkQueue(capacity=4, worker_count=1)
    started = asyncio.Event()
    release = asyncio.Event()
    completed: list[str] = []

    async def work() -> None:
        started.set()
        await release.wait()
        completed.append("done")

    async with asyncio.TaskGroup() as task_group:
        await queue.start(task_group)
        assert await queue.submit("entry:deal-1", work, backpressure=False) is True
        await started.wait()
        assert await queue.submit("entry:deal-1", work, backpressure=False) is False
        release.set()
        await queue.stop()

    assert completed == ["done"]
    assert queue.status()["coalesced_count"] == 1


@pytest.mark.asyncio
async def test_ai_work_queue_rejects_work_outside_lifespan() -> None:
    """Producers must not recreate detached workers after shutdown."""
    queue = AiWorkQueue(capacity=1, worker_count=1)

    assert await queue.submit("entry:deal-1", _noop_work, backpressure=False) is False
    assert queue.status()["rejected_count"] == 1


@pytest.mark.asyncio
async def test_ai_work_queue_records_worker_failure_and_continues() -> None:
    """A failed optional work item should be visible and not kill its worker."""
    queue = AiWorkQueue(capacity=2, worker_count=1)
    completed = asyncio.Event()

    async def fail() -> None:
        raise RuntimeError("provider stalled")

    async def succeed() -> None:
        completed.set()

    async with asyncio.TaskGroup() as task_group:
        await queue.start(task_group)
        await queue.submit("entry:failed", fail, backpressure=False)
        await queue.submit("entry:success", succeed, backpressure=True)
        await asyncio.wait_for(completed.wait(), timeout=1)
        await queue.stop()

    assert queue.status()["last_error"] == "RuntimeError: provider stalled"


async def _noop_work() -> None:
    return None
