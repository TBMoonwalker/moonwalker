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
async def test_ai_work_queue_can_run_compatibility_work_inline() -> None:
    """Direct scripts may explicitly preserve synchronous compatibility."""
    queue = AiWorkQueue(capacity=1, worker_count=1)
    completed = False

    async def work() -> None:
        nonlocal completed
        completed = True

    assert await queue.submit_or_run_inline("entry:deal-1", work) is True
    assert completed is True


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


@pytest.mark.asyncio
async def test_ai_work_queue_rejects_burst_when_capacity_is_saturated() -> None:
    """Non-blocking producers should receive an explicit bounded rejection."""
    queue = AiWorkQueue(capacity=1, worker_count=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def active_work() -> None:
        started.set()
        await release.wait()

    async with asyncio.TaskGroup() as task_group:
        await queue.start(task_group)
        assert await queue.submit("active", active_work, backpressure=False) is True
        await started.wait()
        assert await queue.submit("queued", _noop_work, backpressure=False) is True
        assert await queue.submit("rejected", _noop_work, backpressure=False) is False

        status = queue.status()
        assert status["depth"] == 1
        assert status["pending_count"] == 2
        assert status["rejected_count"] == 1

        release.set()
        await queue.stop()


@pytest.mark.asyncio
async def test_ai_work_queue_cancels_stalled_work_at_drain_deadline() -> None:
    """Shutdown should remain bounded even when a provider call never returns."""
    queue = AiWorkQueue(capacity=1, worker_count=1)
    started = asyncio.Event()
    canceled = asyncio.Event()

    async def stalled_work() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            canceled.set()

    async with asyncio.TaskGroup() as task_group:
        await queue.start(task_group)
        assert await queue.submit("stalled", stalled_work, backpressure=False) is True
        await started.wait()

        loop = asyncio.get_running_loop()
        started_at = loop.time()
        await queue.stop(drain_timeout=0.01)
        elapsed = loop.time() - started_at

    assert elapsed < 0.5
    assert canceled.is_set()
    assert queue.status()["pending_count"] == 0
    assert queue.status()["accepting"] is False


async def _noop_work() -> None:
    return None
