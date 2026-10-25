"""Tests for shared websocket fan-out worker behavior."""

import asyncio

import pytest
from service.websocket_fanout import WebSocketFanout


class _DummyLogger:
    """Minimal logger stub for fan-out tests."""

    def error(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None


@pytest.mark.asyncio
async def test_websocket_fanout_reuses_latest_payload_for_new_subscriber() -> None:
    """A later subscriber should receive cached latest payload without new poll."""
    call_count = 0

    async def _producer() -> str:
        nonlocal call_count
        call_count += 1
        return str(call_count)

    fanout = WebSocketFanout(
        name="test",
        interval_seconds=60,
        producer=_producer,
        logger=_DummyLogger(),
    )

    stream_one = fanout.subscribe()
    stream_two = fanout.subscribe()
    try:
        first = await anext(stream_one)
        second = await anext(stream_two)
        assert first == "1"
        assert second == "1"
        assert call_count == 1
    finally:
        await stream_one.aclose()
        await stream_two.aclose()
        await fanout.stop()


@pytest.mark.asyncio
async def test_websocket_fanout_stops_polling_without_subscribers() -> None:
    """Producer polling should pause when there are no active subscribers."""
    call_count = 0

    async def _producer() -> str:
        nonlocal call_count
        call_count += 1
        return str(call_count)

    fanout = WebSocketFanout(
        name="test",
        interval_seconds=0.05,
        producer=_producer,
        logger=_DummyLogger(),
    )

    stream = fanout.subscribe()
    try:
        await anext(stream)
        await stream.aclose()

        calls_after_disconnect = call_count
        await asyncio.sleep(0.1)
        assert call_count == calls_after_disconnect
    finally:
        await fanout.stop()


@pytest.mark.asyncio
async def test_stopped_fanout_does_not_restart_for_late_websocket_subscription():
    calls = 0

    async def producer():
        nonlocal calls
        calls += 1
        return "unexpected database read after shutdown"

    fanout = WebSocketFanout(
        name="shutdown", interval_seconds=60, producer=producer, logger=_DummyLogger()
    )
    await fanout.start()
    await fanout.stop()
    stream = fanout.subscribe()
    try:
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), timeout=1)
        assert calls == 0
        assert fanout._task is None
    finally:
        await stream.aclose()
        await fanout.stop()


@pytest.mark.asyncio
async def test_explicit_fanout_restart_opens_a_new_lifespan():
    async def producer():
        return "ready"

    fanout = WebSocketFanout(
        name="restart", interval_seconds=60, producer=producer, logger=_DummyLogger()
    )
    await fanout.start()
    await fanout.stop()
    await fanout.start()
    stream = fanout.subscribe()
    try:
        assert await asyncio.wait_for(anext(stream), timeout=1) == "ready"
    finally:
        await stream.aclose()
        await fanout.stop()


@pytest.mark.asyncio
async def test_shutdown_rejects_queued_concurrent_subscribers_without_database_access():
    from unittest.mock import AsyncMock

    producer = AsyncMock(return_value="unexpected")
    fanout = WebSocketFanout(
        name="shutdown-race",
        interval_seconds=60,
        producer=producer,
        logger=_DummyLogger(),
    )
    await fanout.start()
    await fanout._lock.acquire()
    stopping = asyncio.create_task(fanout.stop())
    streams = [fanout.subscribe() for _ in range(8)]
    readers = [asyncio.create_task(anext(stream)) for stream in streams]
    fanout._lock.release()
    try:
        await stopping
        results = await asyncio.wait_for(
            asyncio.gather(*readers, return_exceptions=True), timeout=1
        )
        assert all(isinstance(result, StopAsyncIteration) for result in results)
        producer.assert_not_awaited()
        assert fanout._task is None
    finally:
        for stream in streams:
            await stream.aclose()
        await fanout.stop()


@pytest.mark.asyncio
async def test_current_projection_shares_generation_and_keeps_selections_separate():
    from service.websocket_fanout import CurrentStateProjection

    projection = CurrentStateProjection()
    calls = 0

    async def produce():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return str(calls)

    assert await asyncio.gather(
        projection.read(("scope", "BTC"), produce),
        projection.read(("scope", "BTC"), produce),
    ) == ["1", "1"]
    assert await projection.read(("scope", "ETH"), produce) == "2"
    assert await projection.read(("other-account", "BTC"), produce) == "3"
    projection.invalidate()
    assert await projection.read(("scope", "BTC"), produce) == "4"


@pytest.mark.asyncio
async def test_current_projection_does_not_cache_across_inflight_invalidation():
    from service.websocket_fanout import CurrentStateProjection

    projection = CurrentStateProjection()
    calls = 0

    async def produce():
        nonlocal calls
        calls += 1
        if calls == 1:
            projection.invalidate()
        return str(calls)

    assert await projection.read("BTC", produce) == "1"
    assert await projection.read("BTC", produce) == "2"
