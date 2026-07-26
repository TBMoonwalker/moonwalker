"""Tests for fail-closed dependency lock validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_dependency_lock_checker() -> ModuleType:
    """Load the repository script without depending on the pytest working directory."""
    script_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "check_dependency_locks.py"
    )
    spec = importlib.util.spec_from_file_location(
        "moonwalker_check_dependency_locks",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate_python_lock = _load_dependency_lock_checker().validate_python_lock


def test_validate_python_lock_accepts_hashed_exact_requirement(
    tmp_path: Path,
) -> None:
    """A normal pip-compile requirement should satisfy the lock policy."""
    lock = tmp_path / "requirements.txt"
    lock.write_text(
        "example==1.2.3 \\\n"
        "    --hash=sha256:"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
    )

    assert validate_python_lock(lock) == []


@pytest.mark.parametrize(
    "requirement",
    [
        ("malicious @ " "https://attacker.invalid/malicious-1.0.0-py3-none-any.whl"),
        "git+https://attacker.invalid/repository.git",
        "https://attacker.invalid/malicious-1.0.0-py3-none-any.whl",
        "--trusted-host attacker.invalid",
    ],
)
def test_validate_python_lock_rejects_untrusted_requirement_sources(
    tmp_path: Path,
    requirement: str,
) -> None:
    """Direct URLs, VCS sources, and installer directives must fail closed."""
    lock = tmp_path / "requirements.txt"
    lock.write_text(f"{requirement}\n")

    errors = validate_python_lock(lock)

    assert errors
    assert "unsupported requirement source" in errors[0] or "direct URL" in errors[0]


@pytest.mark.parametrize(
    "injected_line",
    [
        "    malicious @ https://attacker.invalid/malicious.whl",
        "    git+https://attacker.invalid/repository.git",
        "    ./malicious.whl",
        "    --extra-index-url https://attacker.invalid/simple",
    ],
)
def test_validate_python_lock_rejects_indented_requirement_injection(
    tmp_path: Path,
    injected_line: str,
) -> None:
    """Only hash continuations may follow a pinned requirement."""
    lock = tmp_path / "requirements.txt"
    lock.write_text(
        "example==1.2.3 \\\n"
        "    --hash=sha256:"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        f"{injected_line}\n"
    )

    errors = validate_python_lock(lock)

    assert errors
    assert any("unsupported requirement continuation" in error for error in errors)
