#!/usr/bin/env python3
"""Benchmark repeated profit-overall timeline resampling.

Measures the cost of ``Statistic.get_profit_overall_timeline`` under the
loads a single-instance Moonwalker actually sees: a bounded set of dashboard
clients sharing one service and one SQLite database.

The harness is a measurement tool, not a CI gate. It seeds throwaway SQLite
databases at realistic snapshot densities (60 s cadence, as persisted by
``Statistic._store_upnl_snapshot``) and optionally benchmarks a ``sqlite3``
backup copy of a real database (safe while the live app runs; the copy is
opened, the original is never touched).

Scenarios:
  sequential  one client: cold fetch plus five consecutive warm fetches
  concurrent  N clients fetch simultaneously from a cold state
  burst       16 clients staggered 2.5 s apart over ~40 s, two fetches each

Each scenario reports fetch counts, resample (build) counts, wall time, and
per-fetch latency percentiles. Run before and after a change to the timeline
path to compare.

Usage:
    .venv/bin/python scripts/benchmark_timeline.py
    .venv/bin/python scripts/benchmark_timeline.py --db /path/to/trades.sqlite
    .venv/bin/python scripts/benchmark_timeline.py --out-dir DIR
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import model  # noqa: E402
from service.statistic import Statistic  # noqa: E402
from tortoise import Tortoise  # noqa: E402

SNAPSHOT_INTERVAL_SECONDS = 60
SCENARIOS = ("sequential", "concurrent", "burst")
BURST_CLIENTS = 16
BURST_START_STAGGER_SECONDS = 2.5
BURST_FETCH_INTERVAL_SECONDS = 10.0


@dataclass
class ScenarioResult:
    """Measured outcome of one benchmark scenario."""

    name: str
    row_count: int
    fetches: int = 0
    builds: int = 0
    wall_seconds: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)

    def record_latency(self, seconds: float) -> None:
        self.fetches += 1
        self.latencies_ms.append(seconds * 1000.0)

    def percentiles(self) -> dict[str, float]:
        if not self.latencies_ms:
            return {"p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
        ordered = sorted(self.latencies_ms)
        p95_index = max(0, min(len(ordered) - 1, int(0.95 * len(ordered))))
        return {
            "p50_ms": round(statistics.median(ordered), 2),
            "p95_ms": round(ordered[p95_index], 2),
            "max_ms": round(ordered[-1], 2),
        }


def seed_database(db_path: Path, days: int, end: datetime) -> int:
    """Seed 60-second uPNL snapshots ending at ``end`` into ``db_path``."""
    row_count = int(days * 86400 // SNAPSHOT_INTERVAL_SECONDS)
    if db_path.exists():
        db_path.unlink()
    start = end - timedelta(seconds=(row_count - 1) * SNAPSHOT_INTERVAL_SECONDS)
    connect = sqlite3.connect(db_path)
    try:
        connect.execute(
            """
            CREATE TABLE upnl_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp VARCHAR(32) NOT NULL,
                upnl REAL NOT NULL,
                profit_overall REAL NOT NULL,
                funds_locked REAL NOT NULL,
                performance_verified BOOL NOT NULL
            )
            """
        )
        connect.execute("CREATE INDEX idx_upnl_history_ts ON upnl_history (timestamp)")
        profit = 0.0
        rows: list[tuple[str, float, float, float, int]] = []
        for offset in range(row_count):
            timestamp = (
                start + timedelta(seconds=offset * SNAPSHOT_INTERVAL_SECONDS)
            ).isoformat()
            profit += (offset % 7) - 3
            rows.append(
                (timestamp, profit / 10.0, profit, 4200.0 + (offset % 13) * 10.0, 1)
            )
            if len(rows) >= 50_000:
                connect.executemany(
                    "INSERT INTO upnl_history "
                    "(timestamp, upnl, profit_overall, funds_locked, performance_verified) "
                    "VALUES (?, ?, ?, ?, ?)",
                    rows,
                )
                rows = []
        if rows:
            connect.executemany(
                "INSERT INTO upnl_history "
                "(timestamp, upnl, profit_overall, funds_locked, performance_verified) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
        connect.commit()
    finally:
        connect.close()
    return row_count


def copy_database(source: str, destination: Path) -> None:
    """Create a consistent read-only backup copy of ``source``."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(destination))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


async def init_database(db_path: Path) -> None:
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas(safe=True)


class BuildCounter:
    """Count resample builds across the default thread pool."""

    def __init__(self) -> None:
        self.count = 0


def instrument_builds(statistic: Statistic, counter: BuildCounter) -> None:
    """Wrap the build so every resample increments ``counter``.

    The wrapper must stay synchronous: the service runs the build through
    ``asyncio.to_thread`` and expects a plain function.
    """
    original = statistic._build_profit_overall_timeline_sync

    def counting(*args: Any) -> Any:
        counter.count += 1
        return original(*args)

    statistic._build_profit_overall_timeline_sync = counting  # type: ignore[method-assign]


async def run_sequential(statistic: Statistic) -> ScenarioResult:
    """One cold fetch followed by five consecutive warm fetches."""
    result = ScenarioResult(name="sequential", row_count=-1)
    start = time.perf_counter()
    for _ in range(6):
        await _timed_fetch(statistic, result)
    result.wall_seconds = time.perf_counter() - start
    return result


async def run_concurrent(statistic: Statistic, clients: int) -> ScenarioResult:
    result = ScenarioResult(name=f"concurrent-{clients}", row_count=-1)
    start = time.perf_counter()
    await asyncio.gather(*(_timed_fetch(statistic, result) for _ in range(clients)))
    result.wall_seconds = time.perf_counter() - start
    return result


async def _timed_fetch(statistic: Statistic, result: ScenarioResult) -> None:
    fetch_start = time.perf_counter()
    await statistic.get_profit_overall_timeline()
    result.record_latency(time.perf_counter() - fetch_start)


async def run_burst(statistic: Statistic) -> ScenarioResult:
    result = ScenarioResult(name="burst", row_count=-1)
    start = time.perf_counter()
    await asyncio.gather(
        *(_burst_client(statistic, result, index) for index in range(BURST_CLIENTS))
    )
    result.wall_seconds = time.perf_counter() - start
    return result


async def _burst_client(
    statistic: Statistic, result: ScenarioResult, index: int
) -> None:
    await asyncio.sleep(index * BURST_START_STAGGER_SECONDS)
    for _ in range(2):
        await _timed_fetch(statistic, result)
        await asyncio.sleep(BURST_FETCH_INTERVAL_SECONDS)


async def measure_point_statistic(statistic: Statistic) -> dict[str, Any]:
    """Return payload shape and point statistics of one timeline response."""
    timeline = await statistic.get_profit_overall_timeline()
    payload = json.dumps(timeline).encode()
    return {
        "points": len(timeline),
        "payload_bytes": len(payload),
    }


def make_instrumented() -> tuple[Statistic, BuildCounter]:
    statistic = Statistic()
    counter = BuildCounter()
    instrument_builds(statistic, counter)
    return statistic, counter


async def run_scenarios(db_path: Path) -> tuple[list[ScenarioResult], dict[str, Any]]:
    await init_database(db_path)
    row_count = await model.UpnlHistory.all().count()

    results: list[ScenarioResult] = []
    for scenario in SCENARIOS:
        statistic, counter = make_instrumented()
        if scenario == "sequential":
            result = await run_sequential(statistic)
        elif scenario == "concurrent":
            result = await run_concurrent(statistic, clients=4)
        else:
            result = await run_burst(statistic)
        result.row_count = row_count
        result.builds = counter.count
        results.append(result)

    for clients in (8, 16):
        statistic, counter = make_instrumented()
        result = await run_concurrent(statistic, clients=clients)
        result.row_count = row_count
        result.builds = counter.count
        results.append(result)

    point_statistic = await measure_point_statistic(Statistic())
    await Tortoise.close_connections()
    return results, point_statistic


async def main_async(args: argparse.Namespace) -> int:
    scenarios_config: list[tuple[str, Path]] = []
    temp_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "moonwalker-timeline-bench"
    temp_dir.mkdir(parents=True, exist_ok=True)
    end = datetime.now(timezone.utc)
    for label, days in (("16d", 16), ("1y", 365), ("2y", 730)):
        db_path = temp_dir / f"synthetic-{label}.sqlite"
        row_count = seed_database(db_path, days, end)
        scenarios_config.append((f"synthetic-{label} ({row_count} rows)", db_path))
    for name in args.db:
        db_path = temp_dir / f"copy-{Path(name).stem}.sqlite"
        copy_database(name, db_path)
        scenarios_config.append((f"copy of {name}", db_path))

    report: dict[str, Any] = {
        "generated_at": end.isoformat(),
        "python": sys.version.split()[0],
        "scenarios": [],
    }
    for label, db_path in scenarios_config:
        print(f"benchmarking {label} ...", flush=True)
        results, point_statistic = await run_scenarios(db_path)
        report["scenarios"].append(
            {
                "database": label,
                "point_statistic": point_statistic,
                "scenarios": [
                    {
                        "name": item.name,
                        "row_count": item.row_count,
                        "fetches": item.fetches,
                        "builds": item.builds,
                        "wall_seconds": round(item.wall_seconds, 2),
                        **item.percentiles(),
                    }
                    for item in results
                ],
            }
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = end.strftime("%Y-%m-%dT%H%M%SZ")
    json_path = out_dir / f"{stamp}-timeline-server.json"
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"report written to {json_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        action="append",
        default=[],
        metavar="PATH",
        help="real database to benchmark via a backup copy (repeatable)",
    )
    parser.add_argument(
        "--out-dir",
        default=os.path.expanduser(
            "~/.gstack/projects/TBMoonwalker-moonwalker/benchmark-reports"
        ),
        help="directory for the JSON report",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
