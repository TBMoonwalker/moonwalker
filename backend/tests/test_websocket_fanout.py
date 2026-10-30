"""Tests for shared websocket fan-out worker behavior."""

import asyncio

import pytest
from service.websocket_fanout import WebSocketFanout


class _DummyLogger:
    """Minimal logger stub for fan-out tests."""

    def error(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None


@pytest.mark.asyncio
async def test_fresh_subscriber_is_not_blocked_by_hung_regular_producer() -> None:
    started = asyncio.Event()
    never = asyncio.Event()

    async def regular() -> str:
        started.set()
        await never.wait()
        return "old"

    async def fresh() -> str:
        return "fresh"

    fanout = WebSocketFanout(
        name="test",
        interval_seconds=0.01,
        producer=regular,
        fresh_producer=fresh,
        logger=_DummyLogger(),
    )
    normal = fanout.subscribe()
    normal_read = asyncio.create_task(anext(normal))
    recovery = fanout.subscribe(require_new_production=True)
    try:
        await asyncio.wait_for(started.wait(), 1)
        assert await asyncio.wait_for(anext(recovery), 0.2) == "fresh"
    finally:
        normal_read.cancel()
        await asyncio.gather(normal_read, return_exceptions=True)
        await normal.aclose()
        await recovery.aclose()
        await fanout.stop()


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
async def test_fresh_subscriber_waits_for_a_production_started_after_subscribing():
    """An in-flight result cannot satisfy a new subscriber's barrier."""
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def producer():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        return str(calls)

    fanout = WebSocketFanout(
        name="fresh", interval_seconds=0.01, producer=producer, logger=_DummyLogger()
    )
    original = fanout.subscribe()
    first_read = asyncio.create_task(anext(original))
    fresh = fanout.subscribe(require_new_production=True)
    try:
        await asyncio.wait_for(started.wait(), 1)
        fresh_read = asyncio.create_task(anext(fresh))
        await asyncio.sleep(0)
        release.set()
        assert await asyncio.wait_for(first_read, 1) == "1"
        assert int(await asyncio.wait_for(fresh_read, 1)) >= 2
    finally:
        await original.aclose()
        await fresh.aclose()
        await fanout.stop()


@pytest.mark.asyncio
async def test_fresh_subscribers_share_uncached_production():
    """Recovery reads use the uncached producer once for simultaneous clients."""
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    fresh_calls = 0

    async def cached_producer():
        first_started.set()
        await release_first.wait()
        return "cached"

    async def fresh_producer():
        nonlocal fresh_calls
        fresh_calls += 1
        return "fresh"

    fanout = WebSocketFanout(
        name="fresh-source",
        interval_seconds=0.01,
        producer=cached_producer,
        fresh_producer=fresh_producer,
        logger=_DummyLogger(),
    )
    original = fanout.subscribe()
    first = asyncio.create_task(anext(original))
    subscribers = [fanout.subscribe(require_new_production=True) for _ in range(2)]
    readers = []
    try:
        await asyncio.wait_for(first_started.wait(), 1)
        readers = [asyncio.create_task(anext(stream)) for stream in subscribers]
        await asyncio.sleep(0)
        release_first.set()
        assert await asyncio.wait_for(first, 1) == "cached"
        assert await asyncio.wait_for(asyncio.gather(*readers), 1) == ["fresh", "fresh"]
        assert fresh_calls == 1
    finally:
        await original.aclose()
        for stream in subscribers:
            await stream.aclose()
        await fanout.stop()


@pytest.mark.asyncio
async def test_failed_recovery_does_not_block_existing_subscribers():
    """A failed fresh read must neither satisfy recovery nor stall other clients."""
    attempted = asyncio.Event()
    release_retry = asyncio.Event()
    calls = 0

    async def producer():
        return "normal"

    async def fresh_producer():
        nonlocal calls
        calls += 1
        if calls == 1:
            attempted.set()
            raise RuntimeError("source unavailable")
        await release_retry.wait()
        return "fresh"

    fanout = WebSocketFanout(
        name="fresh-failure",
        interval_seconds=0.01,
        producer=producer,
        fresh_producer=fresh_producer,
        logger=_DummyLogger(),
    )
    original = fanout.subscribe()
    recovery = fanout.subscribe(require_new_production=True)
    recovering = None
    try:
        assert await asyncio.wait_for(anext(original), 1) == "normal"
        recovering = asyncio.create_task(anext(recovery))
        await asyncio.wait_for(attempted.wait(), 1)
        assert await asyncio.wait_for(anext(original), 1) == "normal"
        assert not recovering.done()
        release_retry.set()
        assert await asyncio.wait_for(recovering, 1) == "fresh"
    finally:
        if recovering is not None and not recovering.done():
            recovering.cancel()
            await asyncio.gather(recovering, return_exceptions=True)
        await original.aclose()
        await recovery.aclose()
        await fanout.stop()


@pytest.mark.asyncio
async def test_slow_recovery_does_not_block_existing_subscribers():
    """A stalled recovery source must not stop other clients' normal updates."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def producer():
        return "normal"

    async def fresh_producer():
        started.set()
        await release.wait()
        return "fresh"

    fanout = WebSocketFanout(
        name="slow-fresh",
        interval_seconds=0.01,
        producer=producer,
        fresh_producer=fresh_producer,
        logger=_DummyLogger(),
    )
    original = fanout.subscribe()
    recovery = fanout.subscribe(require_new_production=True)
    recovering = None
    try:
        assert await asyncio.wait_for(anext(original), 1) == "normal"
        recovering = asyncio.create_task(anext(recovery))
        await asyncio.wait_for(started.wait(), 1)
        assert await asyncio.wait_for(anext(original), 1) == "normal"
        assert not recovering.done()
        release.set()
        assert await asyncio.wait_for(recovering, 1) == "fresh"
    finally:
        if recovering is not None and not recovering.done():
            recovering.cancel()
            await asyncio.gather(recovering, return_exceptions=True)
        await original.aclose()
        await recovery.aclose()
        await fanout.stop()


@pytest.mark.asyncio
async def test_recovery_subscriber_never_receives_cached_stream_updates():
    """A normal cached payload cannot replace a recovered client's fresh data."""

    async def producer():
        return "cached"

    async def fresh_producer():
        return "fresh"

    fanout = WebSocketFanout(
        name="fresh-only",
        interval_seconds=0.01,
        producer=producer,
        fresh_producer=fresh_producer,
        logger=_DummyLogger(),
    )
    original = fanout.subscribe()
    recovery = fanout.subscribe(require_new_production=True)
    try:
        assert await asyncio.wait_for(anext(original), 1) == "cached"
        assert await asyncio.wait_for(anext(recovery), 1) == "fresh"
        assert await asyncio.wait_for(anext(recovery), 1) == "fresh"
        assert await asyncio.wait_for(anext(original), 1) == "cached"
    finally:
        await original.aclose()
        await recovery.aclose()
        await fanout.stop()


@pytest.mark.asyncio
async def test_abandoned_recovery_read_is_cancelled_before_next_subscriber():
    """A departed recovery subscriber cannot strand later recovery requests."""
    started = asyncio.Event()
    cancelled = asyncio.Event()
    calls = 0

    async def producer():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return "fresh"

    fanout = WebSocketFanout(
        name="cancel-fresh",
        interval_seconds=0.01,
        producer=producer,
        logger=_DummyLogger(),
    )
    first = fanout.subscribe(require_new_production=True)
    reader = asyncio.create_task(anext(first))
    second = None
    try:
        await asyncio.wait_for(started.wait(), 1)
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        await first.aclose()
        await asyncio.wait_for(cancelled.wait(), 1)
        second = fanout.subscribe(require_new_production=True)
        assert await asyncio.wait_for(anext(second), 1) == "fresh"
    finally:
        if second is not None:
            await second.aclose()
        await fanout.stop()


@pytest.mark.asyncio
async def test_recovery_open_trades_bypasses_cache_and_propagates_failure(monkeypatch):
    """Recovery must not treat a failed or cached trade read as current."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from controller import trades as controller

    reader = AsyncMock(return_value=[{"symbol": "BTC/USDC"}])
    monkeypatch.setattr(controller, "trades", SimpleNamespace(get_open_trades=reader))
    monkeypatch.setattr(
        controller,
        "delisting_protection",
        SimpleNamespace(enrich_open_trades=lambda rows: rows),
    )
    assert (
        await controller._build_open_trades_fresh_payload()
        == '[{"symbol": "BTC/USDC"}]'
    )
    reader.assert_awaited_once_with(raise_on_error=True)
    reader.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError):
        await controller._build_open_trades_fresh_payload()


@pytest.mark.asyncio
async def test_recovery_statistics_requires_uncached_available_funds(monkeypatch):
    """A missing exchange balance cannot certify recovery."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from controller import statistics as controller

    balance = AsyncMock(return_value=42.0)
    config = SimpleNamespace(get=lambda *_: "USDC", snapshot=lambda: {})
    monkeypatch.setattr(
        controller, "_get_config_service", AsyncMock(return_value=config)
    )
    monkeypatch.setattr(
        controller, "exchange", SimpleNamespace(get_free_balance_for_asset=balance)
    )
    dashboard = AsyncMock(return_value={"funds_available": 42.0})
    monkeypatch.setattr(
        controller, "statistic", SimpleNamespace(get_profit_for_dashboard=dashboard)
    )
    assert await controller._build_profit_fresh_payload() == '{"funds_available": 42.0}'
    balance.assert_awaited_once_with({}, "USDC", force_refresh=True)
    dashboard.assert_awaited_once_with(42.0, force_refresh=True)
    balance.return_value = None
    with pytest.raises(RuntimeError):
        await controller._build_profit_fresh_payload()


@pytest.mark.asyncio
async def test_recovery_statistics_rejects_account_change_during_refresh(monkeypatch):
    """A balance from an old account cannot certify a new account's dashboard."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from controller import statistics as controller

    settings = {"currency": "USDC", "key": "old"}
    config = SimpleNamespace(
        get=lambda key, default=None: settings.get(key, default),
        snapshot=lambda: dict(settings),
    )
    monkeypatch.setattr(
        controller, "_get_config_service", AsyncMock(return_value=config)
    )
    monkeypatch.setattr(
        controller,
        "exchange",
        SimpleNamespace(get_free_balance_for_asset=AsyncMock(return_value=42)),
    )

    async def dashboard(*_args, **_kwargs):
        settings["key"] = "new"
        return {"funds_available": 42}

    monkeypatch.setattr(
        controller, "statistic", SimpleNamespace(get_profit_for_dashboard=dashboard)
    )
    with pytest.raises(RuntimeError, match="account changed"):
        await controller._build_profit_fresh_payload()


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
