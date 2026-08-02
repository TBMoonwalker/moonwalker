"""Process-kill integration coverage for durable exchange placements."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PROCESS_KILLED_EXIT_CODE = 86
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKER = REPOSITORY_ROOT / "scripts" / "placement_crash_worker.py"
FAKE_EXCHANGE = REPOSITORY_ROOT / "scripts" / "durable_fake_exchange.py"


def _worker_environment() -> dict[str, str]:
    environment = dict(os.environ)
    backend_path = str(REPOSITORY_ROOT / "backend")
    current_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{backend_path}{os.pathsep}{current_python_path}"
        if current_python_path
        else backend_path
    )
    return environment


def _run_worker(
    moonwalker_database: Path,
    exchange_database: Path,
    *arguments: str,
    expected_return_code: int = 0,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            sys.executable,
            str(WORKER),
            "--database",
            str(moonwalker_database),
            "--exchange-database",
            str(exchange_database),
            "--exchange-script",
            str(FAKE_EXCHANGE),
            *arguments,
        ],
        cwd=REPOSITORY_ROOT,
        env=_worker_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == expected_return_code, result.stderr
    return result


def _read_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, result.stderr
    payload = json.loads(lines[-1])
    assert isinstance(payload, dict)
    return payload


def _exchange_summary(exchange_database: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            str(FAKE_EXCHANGE),
            "--database",
            str(exchange_database),
            "summary",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return _read_json(result)


@pytest.mark.parametrize(
    ("crash_point", "expected_orders", "expected_executions", "expected_state"),
    [
        ("before_intent_commit", 0, 0, None),
        (
            "after_intent_commit_before_submission",
            0,
            0,
            "rejected",
        ),
        (
            "after_exchange_acceptance_before_response",
            1,
            1,
            "completed",
        ),
        (
            "after_response_before_trade_persistence",
            1,
            1,
            "completed",
        ),
        ("during_sqlite_transaction", 1, 1, "completed"),
        (
            "after_commit_before_cache_monitoring",
            1,
            1,
            "completed",
        ),
    ],
)
def test_placement_recovers_idempotently_across_process_kill_points(
    tmp_path: Path,
    crash_point: str,
    expected_orders: int,
    expected_executions: int,
    expected_state: str | None,
) -> None:
    moonwalker_database = tmp_path / "moonwalker.sqlite"
    exchange_database = tmp_path / "exchange.sqlite"

    _run_worker(
        moonwalker_database,
        exchange_database,
        "start",
        "--crash-point",
        crash_point,
        expected_return_code=PROCESS_KILLED_EXIT_CODE,
    )
    _run_worker(moonwalker_database, exchange_database, "recover")
    _run_worker(moonwalker_database, exchange_database, "recover")

    local = _read_json(_run_worker(moonwalker_database, exchange_database, "inspect"))
    external = _exchange_summary(exchange_database)

    assert external["order_count"] == expected_orders
    assert external["submit_attempts"] == expected_orders
    assert local == {
        "execution_count": expected_executions,
        "intent_state": expected_state,
        "pending_quote": 0,
        "quarantined_count": 0,
    }


def test_placement_recovers_when_process_dies_during_startup_reconciliation(
    tmp_path: Path,
) -> None:
    moonwalker_database = tmp_path / "moonwalker.sqlite"
    exchange_database = tmp_path / "exchange.sqlite"

    _run_worker(
        moonwalker_database,
        exchange_database,
        "start",
        "--crash-point",
        "after_exchange_acceptance_before_response",
        expected_return_code=PROCESS_KILLED_EXIT_CODE,
    )
    _run_worker(
        moonwalker_database,
        exchange_database,
        "recover",
        "--crash-during-lookup",
        expected_return_code=PROCESS_KILLED_EXIT_CODE,
    )
    _run_worker(moonwalker_database, exchange_database, "recover")
    _run_worker(moonwalker_database, exchange_database, "recover")

    local = _read_json(_run_worker(moonwalker_database, exchange_database, "inspect"))
    external = _exchange_summary(exchange_database)

    assert external == {"order_count": 1, "submit_attempts": 1}
    assert local == {
        "execution_count": 1,
        "intent_state": "completed",
        "pending_quote": 0,
        "quarantined_count": 0,
    }
