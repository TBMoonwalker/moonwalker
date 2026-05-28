"""Regression coverage for the repository startup script."""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
RUN_SCRIPT = ROOT_DIR / "run.sh"


def test_startup_script_syncs_backend_dependencies_before_importing_app() -> None:
    """Startup must not run new code against an old virtual environment."""
    script = RUN_SCRIPT.read_text()

    install_step = "./.venv/bin/python -m pip install -r backend/requirements.txt"
    check_step = "./.venv/bin/python -m pip check"
    import_step = '../.venv/bin/python -c "from controller import route_handlers"'
    launch_step = "../.venv/bin/python app.py"

    assert install_step in script
    assert check_step in script
    assert import_step in script
    assert script.index(install_step) < script.index(check_step)
    assert script.index(check_step) < script.index(import_step)
    assert script.index(import_step) < script.index(launch_step)


def test_startup_script_cleans_lock_when_backend_exits_immediately() -> None:
    """A failed backend launch must not leave Moonwalker looking alive."""
    script = RUN_SCRIPT.read_text()

    assert 'if ! kill -0 "$app_pid" 2>/dev/null; then' in script
    assert 'rm -f "$PID_FILE" "$LOCK_FILE"' in script
    assert "trap 'rm -f \"$LOCK_FILE\"' ERR" in script
