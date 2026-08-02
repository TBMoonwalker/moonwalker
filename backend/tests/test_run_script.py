"""Regression coverage for the repository startup script."""

from pathlib import Path

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

    term_step = 'kill -TERM "$pid"'
    wait_step = 'while kill -0 "$pid" 2>/dev/null; do'
    force_step = 'kill -KILL "$pid" 2>/dev/null || true'

    assert "STOP_TIMEOUT_SECONDS=30" in script
    assert '[[ "$pid" =~ ^[1-9][0-9]*$ ]]' in stop_script
    assert term_step in stop_script
    assert wait_step in stop_script
    assert force_step in stop_script
    assert stop_script.index(term_step) < stop_script.index(wait_step)
    assert stop_script.index(wait_step) < stop_script.index(force_step)
