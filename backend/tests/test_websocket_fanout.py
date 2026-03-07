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
