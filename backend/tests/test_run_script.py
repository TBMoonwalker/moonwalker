"""Regression coverage for the repository startup script."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
RUN_SCRIPT = ROOT_DIR / "run.sh"
INSTALL_SCRIPT = ROOT_DIR / "scripts/install_python_dependencies.sh"


def test_startup_script_builds_verified_environment_before_launching_app() -> None:
    """Startup must validate a new environment before replacing the old one."""
    script = RUN_SCRIPT.read_text()

    install_step = "./scripts/install_python_dependencies.sh"
    check_step = '"$release_venv/bin/python" -m pip check'
    import_step = 'PYTHONPATH=backend "$release_venv/bin/python" -c'
    swap_step = 'ln -s "$release_venv" .venv.next'
    launch_step = "../.venv/bin/python app.py"

    assert install_step in script
    installer = INSTALL_SCRIPT.read_text()
    assert "--require-hashes" in installer
    assert "--only-binary=:all:" in installer
    assert "--force-reinstall" in installer
    assert "--no-deps" in installer
    assert "--no-index" in installer
    assert check_step in script
    assert import_step in script
    assert swap_step in script
    assert script.index(install_step) < script.index(check_step)
    assert script.index(check_step) < script.index(import_step)
    assert script.index(import_step) < script.index(swap_step)
    assert script.index(swap_step) < script.index(launch_step)


def test_startup_script_disables_frontend_dependency_lifecycle_scripts() -> None:
    """Automated npm installs must not execute package lifecycle hooks."""
    script = RUN_SCRIPT.read_text()

    assert "npm ci --ignore-scripts" in script
    assert "npm-run-all" not in script


def test_startup_script_rejects_unsupported_node_before_creating_lock() -> None:
    """Startup must explain how to select Node 24 before changing service state."""
    script = RUN_SCRIPT.read_text()

    runtime_check = "check_frontend_runtime"
    lock_step = 'touch "$LOCK_FILE"'

    assert "Required: Node.js >=24.11.0 <25 and npm >=11 <12." in script
    assert "nvm install" in script
    assert "nvm use" in script
    assert "brew install node@24" in script
    assert 'export PATH="$(brew --prefix node@24)/bin:$PATH"' in script
    assert script.index(runtime_check, script.index("start_services()")) < script.index(
        lock_step, script.index("start_services()")
    )


def test_startup_script_recovers_stale_lock_and_delays_new_lock() -> None:
    """Failed dependency setup must not leave a permanent running marker."""
    script = RUN_SCRIPT.read_text()
    start_function = script.index("start_services()")
    install_step = script.index("npm ci --ignore-scripts", start_function)
    lock_step = script.index('touch "$LOCK_FILE"', start_function)

    assert "Removing stale service lock from an incomplete startup." in script
    assert 'rm -f "$LOCK_FILE" "$PID_FILE"' in script
    assert install_step < lock_step
    assert 'trap \'rm -f "$LOCK_FILE" "$PID_FILE"\' EXIT INT TERM' in script


def test_startup_script_keeps_previous_environment_for_rollback() -> None:
    """The active environment swap must retain one known-good predecessor."""
    script = RUN_SCRIPT.read_text()

    assert "mv .venv .venv.previous" in script
    assert "rm -rf .venv.previous" in script
    assert "mv .venv.previous .venv" in script


def test_startup_script_builds_only_in_the_inactive_environment_slot() -> None:
    """A failed rebuild must never overwrite the currently active venv."""
    script = RUN_SCRIPT.read_text()

    assert 'active_target="$(readlink .venv)"' in script
    assert 'if [ "$(basename "$active_target")" = "slot-a" ]; then' in script
    assert 'release_venv=".venvs/slot-b"' in script
    assert 'release_venv=".venvs/slot-a"' in script
    assert 'rm -rf "$release_venv" .venv.next' in script


def test_startup_script_cleans_lock_when_backend_exits_immediately() -> None:
    """A failed backend launch must not leave Moonwalker looking alive."""
    script = RUN_SCRIPT.read_text()

    assert 'if ! kill -0 "$app_pid" 2>/dev/null; then' in script
    assert 'rm -f "$PID_FILE" "$LOCK_FILE"' in script
    assert 'trap \'rm -f "$LOCK_FILE" "$PID_FILE"\' EXIT INT TERM' in script


def test_stop_script_allows_graceful_shutdown_before_forcing_exit() -> None:
    """Normal stops must give lifespan cleanup time to release owned resources."""
    script = RUN_SCRIPT.read_text()
    stop_function = script.index("stop_services()")
    start_function = script.index("start_services()")
    stop_script = script[stop_function:start_function]

    term_step = 'kill -TERM "$pid" 2>/dev/null || true'
    wait_step = 'while kill -0 "$pid" 2>/dev/null; do'
    force_step = 'kill -KILL "$pid" 2>/dev/null || true'

    assert "STOP_TIMEOUT_SECONDS=30" in script
    assert '[[ "$pid" =~ ^[1-9][0-9]*$ ]]' in stop_script
    assert term_step in stop_script
    assert wait_step in stop_script
    assert force_step in stop_script
    assert stop_script.index(term_step) < stop_script.index(wait_step)
    assert stop_script.index(wait_step) < stop_script.index(force_step)


def _launcher_fixture(
    tmp_path: Path, versions: dict[str, str]
) -> tuple[Path, dict[str, str]]:
    """Run the real launcher against harmless build/interpreter stubs."""
    shutil.copy(RUN_SCRIPT, tmp_path / "run.sh")
    shutil.copy(ROOT_DIR / ".python-version", tmp_path / ".python-version")
    for directory in (
        "frontend/dist/assets",
        "backend/static",
        "backend/templates",
        "bin",
    ):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend/dist/index.html").write_text("fixture")
    (tmp_path / "backend/static/preserved.txt").write_text("original")
    stubs = {
        "node": '#!/bin/sh\nprintf "24.11.0\\n"\n',
        "npm": '#!/bin/sh\nif [ "$1" = "--version" ]; then printf "11.0.0\\n"; else printf "npm %s\\n" "$*" >> "$LAUNCH_TRACE"; fi\n',
    }
    for name, version in versions.items():
        stubs[name] = f'''#!/bin/sh
if [ "$1" = "-c" ]; then
    printf "{version}\\n"
else
    printf "%s %s\\n" "$0" "$*" >> "$LAUNCH_TRACE"
    exit 42
fi
'''
    for name, contents in stubs.items():
        executable = tmp_path / "bin" / name
        executable.write_text(contents)
        executable.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "LAUNCH_TRACE": str(tmp_path / "trace"),
    }
    env.pop("MOONWALKER_PYTHON", None)
    return tmp_path, env


@pytest.mark.parametrize(
    "versions,expected",
    [
        ({"python3": "3.9", "python3.14": "3.14"}, "python3.14"),
        ({"python3": "3.14", "python3.14": "3.14"}, "python3"),
        ({"python3": "3.15", "python3.14": "3.14"}, "python3.14"),
    ],
)
def test_launcher_uses_verified_python_when_generic_command_is_wrong(
    tmp_path: Path, versions: dict[str, str], expected: str
) -> None:
    root, env = _launcher_fixture(tmp_path, versions)
    result = subprocess.run(
        ["/bin/bash", "run.sh", "start"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    # The selected venv stub deliberately stops before dependency installation.
    assert result.returncode == 42, result.stdout + result.stderr
    trace = (root / "trace").read_text()
    assert f"/bin/{expected} -m venv .venvs/slot-a" in trace
    assert not (root / "moonwalker.lock").exists()


def test_missing_python_fails_before_build_or_asset_replacement(tmp_path: Path) -> None:
    root, env = _launcher_fixture(tmp_path, {"python3": "3.9"})
    result = subprocess.run(
        ["/bin/bash", "run.sh", "start"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "Python 3.14 is required" in result.stdout + result.stderr
    assert (root / "backend/static/preserved.txt").read_text() == "original"
    assert not (root / "trace").exists()
    assert not (root / ".venvs").exists()


def test_explicit_python_override_is_verified_and_never_silently_replaced(
    tmp_path: Path,
) -> None:
    root, env = _launcher_fixture(
        tmp_path, {"python3": "3.14", "python3.14": "3.14", "custom python": "3.9"}
    )
    env["MOONWALKER_PYTHON"] = str(root / "bin" / "custom python")
    result = subprocess.run(
        ["/bin/bash", "run.sh", "start"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert not (root / "trace").exists()
    assert (root / "backend/static/preserved.txt").read_text() == "original"
    (root / "bin" / "custom python").write_text(
        (root / "bin" / "python3.14").read_text()
    )
    success = subprocess.run(
        ["/bin/bash", "run.sh", "start"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert success.returncode == 42, success.stdout + success.stderr
    assert "/bin/custom python -m venv" in (root / "trace").read_text()
