#!/usr/bin/env python3
"""Enforce ratcheted backend coverage floors from coverage.py JSON output."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

GLOBAL_LINE_FLOOR = 71.0
GLOBAL_BRANCH_FLOOR = 57.0
CRITICAL_MODULE_BRANCH_FLOORS = {
    "backend/controller/config.py": 65.0,
    "backend/service/ai_trust.py": 72.0,
    "backend/service/ai_trust_analytics.py": 95.0,
    "backend/service/ai_trust_calibration.py": 90.0,
    "backend/service/coin_market_cap.py": 76.0,
    "backend/service/config.py": 72.0,
    "backend/service/dca_decision.py": 100.0,
    "backend/service/exchange_capabilities.py": 87.0,
    "backend/service/lifecycle_mutation.py": 100.0,
    "backend/service/lifecycle_snapshot.py": 100.0,
    "backend/service/order_mutation_result.py": 100.0,
    "backend/service/orders.py": 67.0,
    "backend/service/placement_intents.py": 84.0,
    "backend/service/placement_reconciliation.py": 65.0,
    "backend/service/placement_recovery.py": 71.0,
    "backend/service/placement_workflow.py": 87.0,
    "backend/service/runtime_services.py": 75.0,
    "backend/service/schema_migrations.py": 85.0,
    "backend/service/signal_runtime.py": 77.0,
    "backend/service/strategy_ir.py": 76.0,
    "backend/service/strategy_persistence.py": 67.0,
}


def _branch_percentage(summary: dict[str, Any]) -> float:
    """Return branch coverage without conflating it with line coverage."""
    return float(summary.get("percent_branches_covered", 0.0))


def validate_coverage(payload: dict[str, Any]) -> list[str]:
    """Return coverage-floor failures for a coverage.py JSON payload."""
    failures: list[str] = []
    totals = payload.get("totals", {})
    line_coverage = float(totals.get("percent_covered", 0.0))
    branch_coverage = float(totals.get("percent_branches_covered", 0.0))

    if line_coverage < GLOBAL_LINE_FLOOR:
        failures.append(
            f"global combined coverage {line_coverage:.2f}% "
            f"is below {GLOBAL_LINE_FLOOR:.2f}%"
        )
    if branch_coverage < GLOBAL_BRANCH_FLOOR:
        failures.append(
            f"global branch coverage {branch_coverage:.2f}% "
            f"is below {GLOBAL_BRANCH_FLOOR:.2f}%"
        )

    files = payload.get("files", {})
    for module, floor in CRITICAL_MODULE_BRANCH_FLOORS.items():
        result = next(
            (
                candidate
                for path, candidate in files.items()
                if Path(path).as_posix().endswith(module)
            ),
            None,
        )
        if not isinstance(result, dict):
            failures.append(f"coverage output is missing critical module {module}")
            continue
        coverage = _branch_percentage(result.get("summary", {}))
        if coverage < floor:
            failures.append(
                f"{module} branch coverage {coverage:.2f}% is below {floor:.2f}%"
            )
    return failures


def main() -> int:
    """Validate the coverage JSON path supplied on the command line."""
    if len(sys.argv) != 2:
        print("Usage: check_coverage_thresholds.py COVERAGE_JSON")
        return 2

    path = Path(sys.argv[1])
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: unable to read coverage report {path}: {exc}")
        return 2

    failures = validate_coverage(payload)
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1

    print(
        "Coverage floors passed "
        f"(global >= {GLOBAL_LINE_FLOOR:.0f}%, "
        f"branches >= {GLOBAL_BRANCH_FLOOR:.0f}%, "
        f"{len(CRITICAL_MODULE_BRANCH_FLOORS)} critical modules ratcheted)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
