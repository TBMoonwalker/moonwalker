"""Differential tests: indexed bucket walk vs the pandas resample reference.

``Statistic._fetch_profit_overall_timeline`` resolves each resample bucket
with an indexed ``LIMIT 1`` seek for its last verified snapshot. These
tests prove that its output is point-for-point identical to the original
full-history ``resample(...).last()`` pipeline (kept below as a reference
implementation) across adversarial boundary, duplicate, sparse and empty
fixtures, for both aligned and sub-second-offset rebuild times.
"""

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import model
import pandas as pd
import pytest
from service.statistic import Statistic
from tortoise import Tortoise

# A rebuild instant on the 15-minute grid (zero microsecond) and one with a
# fractional second, so the slice starts land on and off the bucket grids.
NOW_ALIGNED = datetime(2026, 11, 10, 9, 45, 0, tzinfo=UTC)
NOW_OFFSET = datetime(2026, 11, 10, 9, 47, 33, 123456, tzinfo=UTC)

# Adversarial rows as ``(timestamp, profit_overall, verified)``;
# ``funds_locked`` mirrors ``profit_overall`` so the winning row is
# identifiable in the output.
ADVERSARIAL_ROWS: list[tuple[datetime, float, bool]] = [
    # year slice: horizon edge (0.12s / 1us before and at the start)
    (datetime(2025, 11, 10, 9, 47, 33, tzinfo=UTC), 1001.0, True),
    (datetime(2025, 11, 10, 9, 47, 33, 123456, tzinfo=UTC), 1002.0, True),
    (datetime(2025, 11, 10, 9, 47, 33, 123455, tzinfo=UTC), 1401.0, True),
    # year slice: Monday-anchored week bins, Sunday labels
    (datetime(2025, 11, 16, 23, 59, 59, tzinfo=UTC), 1003.0, True),
    (datetime(2025, 11, 17, 0, 0, 0, tzinfo=UTC), 1004.0, True),
    (datetime(2026, 2, 21, 23, 59, 59, tzinfo=UTC), 1005.0, True),
    (datetime(2026, 2, 22, 0, 0, 0, tzinfo=UTC), 1006.0, True),
    (datetime(2026, 2, 23, 0, 0, 0, tzinfo=UTC), 1007.0, True),
    (datetime(2026, 2, 23, 0, 0, 0, 1, tzinfo=UTC), 1008.0, True),
    (datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC), 1009.0, True),
    # month/week boundary straddle: label collision across slices
    (datetime(2026, 10, 11, 9, 47, 33, tzinfo=UTC), 1010.0, True),
    (datetime(2026, 10, 11, 9, 47, 33, 123456, tzinfo=UTC), 1011.0, True),
    (datetime(2026, 10, 11, 10, 0, 0, tzinfo=UTC), 1012.0, True),
    # month slice: day bins around midnight
    (datetime(2026, 10, 20, 23, 59, 59, tzinfo=UTC), 1101.0, True),
    (datetime(2026, 10, 21, 0, 0, 0, tzinfo=UTC), 1102.0, True),
    (datetime(2026, 11, 3, 9, 47, 33, tzinfo=UTC), 1103.0, True),
    (datetime(2026, 11, 3, 9, 47, 33, 123456, tzinfo=UTC), 1104.0, True),
    # week slice: 4h bins, exact boundaries and sub-second pairs
    (datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC), 1201.0, True),
    (datetime(2026, 11, 4, 4, 0, 0, tzinfo=UTC), 1202.0, True),
    (datetime(2026, 11, 4, 4, 0, 0, 1, tzinfo=UTC), 1203.0, True),
    (datetime(2026, 11, 5, 0, 0, 0, tzinfo=UTC), 1204.0, True),
    (datetime(2026, 11, 9, 8, 0, 0, tzinfo=UTC), 1205.0, True),
    (datetime(2026, 11, 9, 9, 47, 33, 123446, tzinfo=UTC), 1206.0, True),
    # day slice: 15min bins, exact boundaries, duplicate timestamps
    (datetime(2026, 11, 9, 10, 29, 59, 999999, tzinfo=UTC), 1303.0, True),
    (datetime(2026, 11, 9, 10, 30, 0, tzinfo=UTC), 1301.0, True),
    (datetime(2026, 11, 9, 10, 30, 0, 1, tzinfo=UTC), 1302.0, True),
    (datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC), 1304.0, True),
    (datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC), 1305.0, True),
    (NOW_OFFSET, 1306.0, True),
    # unverified rows must never reach the timeline
    (datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC), 9998.0, False),
    (datetime(2026, 11, 9, 11, 0, 0, tzinfo=UTC), 9999.0, False),
]

SPARSE_ROWS: list[tuple[datetime, float, bool]] = [
    (datetime(2025, 11, 10, 0, 0, 0, tzinfo=UTC), 1.0, True),
    (datetime(2026, 4, 15, 6, 30, 45, tzinfo=UTC), 2.0, True),
    (datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC), 3.0, True),
    (datetime(2026, 11, 5, 16, 30, 0, tzinfo=UTC), 4.0, True),
    (datetime(2026, 11, 9, 23, 59, 59, tzinfo=UTC), 5.0, True),
]


def reference_timeline(
    rows: list[tuple[Any, Any, Any]],
    now: datetime,
    horizons: dict[str, timedelta],
) -> list[dict[str, Any]]:
    """The original full-history resample pipeline, kept as a test oracle.

    Mirrors the pre-2026-11 implementation of
    ``Statistic._build_profit_overall_timeline_sync``: resample each slice
    of the verified horizon with pandas ``last()``, then concatenate in
    ascending slice order with later slices winning on equal labels.
    """
    df = pd.DataFrame(
        rows,
        columns=["timestamp", "profit_overall", "funds_locked"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp")
    df = df[~df.index.duplicated(keep="last")]

    year_start = now - horizons["year"]
    day_start = now - horizons["day"]
    week_start = now - horizons["week"]
    month_start = now - horizons["month"]

    frames: list[pd.DataFrame] = []

    year_slice = df[(df.index >= year_start) & (df.index < month_start)]
    if not year_slice.empty:
        frames.append(year_slice.resample("1W").last().dropna())

    month_slice = df[(df.index >= month_start) & (df.index < week_start)]
    if not month_slice.empty:
        frames.append(month_slice.resample("1D").last().dropna())

    week_slice = df[(df.index >= week_start) & (df.index < day_start)]
    if not week_slice.empty:
        frames.append(week_slice.resample("4h").last().dropna())

    day_slice = df[df.index >= day_start]
    if not day_slice.empty:
        frames.append(day_slice.resample("15min").last().dropna())

    if not frames:
        return []

    merged = pd.concat(frames).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]

    return [
        {
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "profit_overall": float(row["profit_overall"]),
            "funds_locked": float(row["funds_locked"]),
        }
        for timestamp, row in merged.iterrows()
    ]


def dense_seed(db_path: Path, end: datetime, days: int) -> int:
    """Seed ``days`` of 60-second snapshots in the production storage format.

    Tortoise persists aware UTC datetimes as space-separated strings with a
    ``+00:00`` suffix, fractional seconds omitted only when the microsecond
    is zero. The bucket walk compares its bounds against those strings
    lexicographically, so the fixture must match that format exactly.
    """
    row_count = int(days * 86400 // 60)
    start = end - timedelta(seconds=(row_count - 1) * 60)
    raw = sqlite3.connect(db_path)
    try:
        raw.execute("BEGIN")
        profit = 0.0
        for offset in range(row_count):
            value = start + timedelta(seconds=offset * 60)
            if value.microsecond:
                literal = value.strftime("%Y-%m-%d %H:%M:%S.%f") + "+00:00"
            else:
                literal = value.strftime("%Y-%m-%d %H:%M:%S") + "+00:00"
            profit += (offset % 7) - 3
            raw.execute(
                "INSERT INTO upnl_history (timestamp, upnl, profit_overall,"
                " funds_locked, performance_verified) VALUES (?,?,?,?,1)",
                (literal, profit / 10.0, profit, 4200.0 + (offset % 13) * 10.0),
            )
        raw.execute("COMMIT")
    finally:
        raw.close()
    return row_count


async def _seed_rows(rows: list[tuple[datetime, float, bool]]) -> None:
    """Seed snapshots at exact ``(timestamp, profit_overall, verified)``."""
    for timestamp, profit_overall, verified in rows:
        await model.UpnlHistory.create(
            timestamp=timestamp,
            upnl=profit_overall / 2.0,
            profit_overall=profit_overall,
            funds_locked=profit_overall,
            performance_verified=verified,
        )


async def _reference_rows(
    now: datetime, horizons: dict[str, timedelta]
) -> list[tuple[Any, Any, Any]]:
    """Fetch the verified horizon exactly the way the rebuild does.

    The ``id`` tie-break on equal timestamps is deliberate: it matches the
    production query's ``ORDER BY timestamp DESC, id DESC LIMIT 1`` and
    keeps the oracle deterministic where a plain timestamp sort is not.
    """
    return (
        await model.UpnlHistory.filter(
            timestamp__gte=now - horizons["year"], performance_verified=True
        )
        .order_by("timestamp", "id")
        .values_list("timestamp", "profit_overall", "funds_locked")
    )


async def _assert_matches_reference(statistic: Statistic, now: datetime) -> None:
    horizons = statistic.timeline_horizons
    rows = await _reference_rows(now, horizons)
    expected = reference_timeline(rows, now, horizons)
    actual = await statistic._fetch_profit_overall_timeline(now)
    assert actual == expected


def _init_db(tmp_path, monkeypatch) -> None:
    """Common fixture setup: chdir + schema, matching the cache tests."""
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))


async def _make_db(tmp_path, monkeypatch) -> None:
    _init_db(tmp_path, monkeypatch)
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'test.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()


@pytest.mark.asyncio
async def test_prewin_matches_reference_adversarial(tmp_path, monkeypatch) -> None:
    await _make_db(tmp_path, monkeypatch)
    try:
        await _seed_rows(ADVERSARIAL_ROWS)
        statistic = Statistic()
        for now in (NOW_ALIGNED, NOW_OFFSET):
            await _assert_matches_reference(statistic, now)
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_prewin_matches_reference_sparse(tmp_path, monkeypatch) -> None:
    await _make_db(tmp_path, monkeypatch)
    try:
        await _seed_rows(SPARSE_ROWS)
        statistic = Statistic()
        for now in (NOW_ALIGNED, NOW_OFFSET):
            await _assert_matches_reference(statistic, now)
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_prewin_empty_history(tmp_path, monkeypatch) -> None:
    await _make_db(tmp_path, monkeypatch)
    try:
        statistic = Statistic()
        assert await statistic._fetch_profit_overall_timeline(NOW_ALIGNED) == []
        assert await statistic.get_profit_overall_timeline() == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_prewin_matches_reference_dense_60s(tmp_path, monkeypatch) -> None:
    """Dense 60-second cadence: every bucket of every slice is filled.

    The sparse fixtures leave most buckets empty; this seeds a full year
    at the production snapshot cadence so all four resolution grids (15min,
    4h, 1d, Monday-anchored 1w) are exercised with filled buckets, for both
    an aligned (no fractional second) and an offset rebuild instant.
    """
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    now = datetime.now(UTC)
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    try:
        dense_seed(db_path, now, 365)
        statistic = Statistic()
        for probe in (now.replace(microsecond=0), now.replace(microsecond=123456)):
            await _assert_matches_reference(statistic, probe)
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_prewin_public_api_matches_reference(tmp_path, monkeypatch) -> None:
    await _make_db(tmp_path, monkeypatch)
    try:
        await _seed_rows(ADVERSARIAL_ROWS)
        statistic = Statistic()
        now = datetime.now(UTC)

        public = await statistic.get_profit_overall_timeline()
        expected = reference_timeline(
            await _reference_rows(now, statistic.timeline_horizons),
            now,
            statistic.timeline_horizons,
        )

        assert public == expected
    finally:
        await Tortoise.close_connections()
