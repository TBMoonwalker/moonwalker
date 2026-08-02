"""Regression tests for branch-specific critical-module coverage ratchets."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COVERAGE_SCRIPT = REPOSITORY_ROOT / "scripts" / "check_coverage_thresholds.py"


def _load_coverage_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "check_coverage_thresholds",
        COVERAGE_SCRIPT,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


coverage_module = _load_coverage_module()


def _passing_payload() -> dict:
    files = {
        f"/workspace/{module}": {
            "summary": {
                "percent_covered": 100.0,
                "percent_branches_covered": floor,
            }
        }
        for module, floor in (coverage_module.CRITICAL_MODULE_BRANCH_FLOORS.items())
    }
    return {
        "totals": {
            "percent_covered": 100.0,
            "percent_branches_covered": 100.0,
        },
        "files": files,
    }


def test_critical_module_ratchet_uses_branch_coverage() -> None:
    payload = _passing_payload()
    module, floor = next(iter(coverage_module.CRITICAL_MODULE_BRANCH_FLOORS.items()))
    payload["files"][f"/workspace/{module}"]["summary"].update(
        {
            "percent_covered": 100.0,
            "percent_branches_covered": floor - 1.0,
        }
    )

    failures = coverage_module.validate_coverage(payload)

    assert failures == [
        f"{module} branch coverage {floor - 1.0:.2f}% " f"is below {floor:.2f}%"
    ]


def test_missing_critical_module_fails_the_ratchet() -> None:
    payload = _passing_payload()
    missing_module = next(iter(coverage_module.CRITICAL_MODULE_BRANCH_FLOORS))
    del payload["files"][f"/workspace/{missing_module}"]

    failures = coverage_module.validate_coverage(payload)

    assert failures == [f"coverage output is missing critical module {missing_module}"]
