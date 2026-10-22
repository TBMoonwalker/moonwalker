"""Idle clients wait on a change event; slow dashboards cannot grow a queue."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from controller import accumulation as controller
from litestar import Litestar
from litestar.exceptions import WebSocketDisconnect
from litestar.middleware import DefineMiddleware
from litestar.testing import TestClient
from service.accumulation_status_events import AccumulationStatusEvents
from service.origin_policy import WebSocketOriginMiddleware


@pytest.mark.asyncio
async def test_initial_snapshot_and_coalesced_multiclient_delivery():
    events = AccumulationStatusEvents()
    first, second = events.subscribe(), events.subscribe()
    assert await anext(first) is None
    assert await anext(second) is None
    pending = asyncio.create_task(anext(first))
    await asyncio.sleep(0)
    assert not pending.done()
    for _ in range(1000):
        events.publish()
    assert await asyncio.wait_for(pending, 0.2) is None
    assert await anext(second) is None
    assert all(queue.empty() for queue in events._queues)
    events.close()
    with pytest.raises(StopAsyncIteration):
        await anext(first)
    with pytest.raises(StopAsyncIteration):
        await anext(second)
    assert not events._queues


@pytest.mark.asyncio
async def test_disconnect_does_not_leave_a_subscriber():
    events = AccumulationStatusEvents()
    subscriber = events.subscribe()
    await anext(subscriber)
    await subscriber.aclose()
    assert not events._queues
    events.close()
    with pytest.raises(StopAsyncIteration):
        await anext(events.subscribe())


def test_real_websocket_pushes_to_two_clients_and_preserves_origin_gate(monkeypatch):
    events = AccumulationStatusEvents()
    runtime = SimpleNamespace(
        ready=True,
        status={},
        wait_conditions={},
        current_account_scope="account",
        status_events=events,
    )
    detail = {"symbol": "BTC/USDC", "revision": 1, "runtime_wait_reason": "WAIT_DATA"}
    page = {"activations": [detail], "next_after": None}
    producer = AsyncMock(
        side_effect=lambda *args, **kwargs: {
            "type": "snapshot",
            "page": page,
            "detail": dict(detail),
        }
    )
    monkeypatch.setattr(controller, "_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr(controller, "accumulation_stream_snapshot", producer)
    app = Litestar(
        route_handlers=[controller.stream_status],
        middleware=[DefineMiddleware(WebSocketOriginMiddleware)],
        openapi_config=None,
    )
    with TestClient(app, base_url="http://localhost") as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/accumulation/stream", headers={"origin": "https://outside.example"}
            ):
                pass
        assert not producer.called
        with client.websocket_connect(
            "/accumulation/stream?symbol=BTC%2FUSDC"
        ) as first:
            assert first.receive_json()["detail"]["revision"] == 1
            with client.websocket_connect(
                "/accumulation/stream?symbol=BTC%2FUSDC"
            ) as second:
                assert second.receive_json()["detail"]["revision"] == 1

                async def change():
                    detail.update(revision=2, runtime_wait_reason="WAIT_DEPTH")
                    events.publish()

                with client.portal() as portal:
                    portal.call(change)
                assert (
                    first.receive_json()["detail"]["runtime_wait_reason"]
                    == "WAIT_DEPTH"
                )
                assert second.receive_json()["detail"]["revision"] == 2
                assert producer.await_count == 4
    assert not events.connected
