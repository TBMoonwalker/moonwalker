"""Tests for the short-lived server cache on the profit-overall timeline."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import model
import pytest
from service.housekeeper import Housekeeper
from service.statistic import Statistic
from tortoise import Tortoise
from tortoise.exceptions import BaseORMException


class _FakeOrmError(BaseORMException):
    """Test-only ORM failure used to exercise the uncached error path."""


def _instrument_builds(statistic: Statistic) -> list[int]:
    """Return a counter incremented on every timeline rebuild.

    The wrapper must stay asynchronous: the service awaits the rebuild
    directly on the event loop.
    """
    builds: list[int] = [0]
    original = statistic._fetch_profit_overall_timeline

    async def counting(now: datetime) -> Any:
        builds[0] += 1
        return await original(now)

    statistic._fetch_profit_overall_timeline = counting  # type: ignore[method-assign]
    return builds


async def _seed_history(
    rows: list[tuple[timedelta, float, float]],
) -> None:
    """Seed uPNL snapshots offset from now with (profit, funds_locked)."""
    now = datetime.now(UTC)
    for offset, profit_overall, funds_locked in rows:
        await model.UpnlHistory.create(
            timestamp=now - offset,
            upnl=profit_overall / 2.0,
            profit_overall=profit_overall,
            funds_locked=funds_locked,
        )


@pytest.mark.asyncio
async def test_timeline_fetch_caches_within_ttl(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'test.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        await _seed_history(
            [
                (timedelta(hours=2), 10.0, 100.0),
                (timedelta(hours=1), 11.0, 101.0),
            ]
        )
        statistic = Statistic()
        builds = _instrument_builds(statistic)

        first = await statistic.get_profit_overall_timeline()
        second = await statistic.get_profit_overall_timeline()

        assert first == second
        assert len(first) >= 1
        assert builds == [1]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_fetched_timeline_list_does_not_alias_cache(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'test.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        await _seed_history([(timedelta(hours=1), 10.0, 100.0)])
        statistic = Statistic()
        _instrument_builds(statistic)

        first = await statistic.get_profit_overall_timeline()
        original = list(first)
        first.append(
            {"timestamp": "tampered", "profit_overall": 0.0, "funds_locked": 0.0}
        )

        second = await statistic.get_profit_overall_timeline()

        assert second == original
        assert statistic._timeline_cache is not first
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_timeline_cache_invalidated_by_snapshot_write(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'test.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        await _seed_history([(timedelta(hours=2), 10.0, 100.0)])
        statistic = Statistic()
        statistic.snapshot_interval_seconds = 0
        builds = _instrument_builds(statistic)

        first = await statistic.get_profit_overall_timeline()
        await statistic._store_upnl_snapshot(
            {"upnl": 49.0, "profit_overall": 99.0, "funds_locked": 200.0}
        )
        second = await statistic.get_profit_overall_timeline()

        # The stored snapshot is visible to the next fetch (bucket update).
        assert second[-1]["profit_overall"] == 99.0
        assert second[-1]["funds_locked"] == 200.0
        assert builds == [2]
        assert second[-1]["timestamp"] >= first[-1]["timestamp"]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_snapshot_write_from_other_instance_invalidates_cache(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'test.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        await _seed_history([(timedelta(hours=2), 10.0, 100.0)])
        serving = Statistic()
        other = Statistic()
        other.snapshot_interval_seconds = 0
        builds = _instrument_builds(serving)

        await serving.get_profit_overall_timeline()
        await other._store_upnl_snapshot(
            {"upnl": 49.0, "profit_overall": 99.0, "funds_locked": 200.0}
        )
        second = await serving.get_profit_overall_timeline()

        # The write happened on a different Statistic instance (as the DCA
        # engine and signal plugins do), yet the serving cache rebuilt.
        assert second[-1]["profit_overall"] == 99.0
        assert builds == [2]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_timeline_cache_expires_after_ttl(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'test.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        await _seed_history([(timedelta(hours=1), 10.0, 100.0)])
        statistic = Statistic()
        builds = _instrument_builds(statistic)
        monkeypatch.setattr("service.statistic.TIMELINE_CACHE_TTL_SECONDS", 0)

        await statistic.get_profit_overall_timeline()
        await statistic.get_profit_overall_timeline()

        assert builds == [2]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_concurrent_timeline_fetches_share_one_build(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'test.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        await _seed_history(
            [
                (timedelta(hours=3), 9.0, 99.0),
                (timedelta(hours=2), 10.0, 100.0),
                (timedelta(hours=1), 11.0, 101.0),
            ]
        )
        statistic = Statistic()
        builds = _instrument_builds(statistic)

        results = await asyncio.gather(
            *(statistic.get_profit_overall_timeline() for _ in range(8))
        )

        assert builds == [1]
        assert all(result == results[0] for result in results)
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_timeline_cache_matches_uncached_build(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'test.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        await _seed_history(
            [
                (timedelta(days=100), 1.0, 10.0),
                (timedelta(days=20), 5.0, 50.0),
                (timedelta(days=3), 8.0, 80.0),
                (timedelta(hours=3), 9.0, 90.0),
                (timedelta(hours=1), 10.0, 100.0),
            ]
        )
        cached_statistic = Statistic()
        uncached_statistic = Statistic()

        cached = await cached_statistic.get_profit_overall_timeline()
        uncached = await uncached_statistic.get_profit_overall_timeline()

        assert cached == uncached
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_timeline_query_error_is_not_cached(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'test.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        statistic = Statistic()

        class _BrokenConnection:
            async def execute_query(self, *_args: Any, **_kwargs: Any) -> Any:
                raise _FakeOrmError("database unavailable")

        class _BrokenTortoise:
            @staticmethod
            def get_connection(_alias: str) -> Any:
                return _BrokenConnection()

        monkeypatch.setattr("service.statistic.Tortoise", _BrokenTortoise)

        assert await statistic.get_profit_overall_timeline() == []
        assert await statistic.get_profit_overall_timeline() == []
        assert statistic._timeline_cache is None
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_retention_cleanup_fires_hook_and_clears_cache(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'test.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        now = datetime.now(UTC)
        await model.UpnlHistory.create(
            timestamp=now - timedelta(days=40),
            upnl=0.5,
            profit_overall=1.0,
            funds_locked=10.0,
        )
        await model.UpnlHistory.create(
            timestamp=now - timedelta(hours=1),
            upnl=5.0,
            profit_overall=10.0,
            funds_locked=100.0,
        )
        statistic = Statistic()
        builds = _instrument_builds(statistic)
        housekeeper = Housekeeper()
        housekeeper.config = {"upnl_housekeeping_interval": 30}
        housekeeper.on_upnl_history_changed = statistic.invalidate_timeline_cache

        await statistic.get_profit_overall_timeline()
        rows_before = await model.UpnlHistory.all().count()
        await housekeeper._cleanup_upnl_history(now)
        timeline = await statistic.get_profit_overall_timeline()

        assert rows_before - await model.UpnlHistory.all().count() == 1
        assert builds == [2]
        # The pruned 40-day-old point is gone; only the recent one remains.
        assert len(timeline) == 1
        assert timeline[0]["profit_overall"] == 10.0
        assert timeline[0]["funds_locked"] == 100.0
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_retention_cleanup_without_deletions_does_not_fire_hook(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'test.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    try:
        now = datetime.now(UTC)
        await model.UpnlHistory.create(
            timestamp=now - timedelta(hours=1),
            upnl=5.0,
            profit_overall=10.0,
            funds_locked=100.0,
        )
        statistic = Statistic()
        builds = _instrument_builds(statistic)
        housekeeper = Housekeeper()
        housekeeper.config = {"upnl_housekeeping_interval": 30}
        housekeeper.on_upnl_history_changed = statistic.invalidate_timeline_cache

        rows_before = await model.UpnlHistory.all().count()
        await statistic.get_profit_overall_timeline()
        await housekeeper._cleanup_upnl_history(now)
        await statistic.get_profit_overall_timeline()

        assert await model.UpnlHistory.all().count() == rows_before
        assert builds == [1]
    finally:
        await Tortoise.close_connections()
