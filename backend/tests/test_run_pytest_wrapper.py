import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest


def _run_scripted_pytest(
    tmp_path: Path, script: str
) -> subprocess.CompletedProcess[str]:
    """Exercise the real watchdog with controlled child output and lifetime."""
    (tmp_path / "pytest.py").write_text(script, encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "scripts/run_pytest.py"),
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={
            **os.environ,
            "PYTHONPATH": str(tmp_path),
            "PYTEST_TIMEOUT": "2",
            "PYTEST_POST_SUMMARY_TIMEOUT": "0",
        },
    )
    try:
        stdout, stderr = process.communicate(timeout=10)
        return subprocess.CompletedProcess(
            process.args, process.returncode, stdout, stderr
        )
    finally:
        # A broken watchdog must not leave its deliberately hung child behind.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


@pytest.mark.parametrize("prefix", ["", "test_example.py . [100%]\n"])
@pytest.mark.parametrize("duration", ["0.10s", "227.83s (0:03:47)"])
@pytest.mark.parametrize(("outcome", "exit_code"), [("1 passed", 0), ("1 failed", 1)])
def test_watchdog_reads_complete_summary_before_child_exit(
    tmp_path: Path, prefix: str, duration: str, outcome: str, exit_code: int
) -> None:
    """A single pipe write must expose every line, including long-run summaries."""
    summary = f"================ {outcome} in {duration} =================\n"
    payload = (prefix + summary).encode()
    result = _run_scripted_pytest(
        tmp_path,
        f"import os, threading\nos.write(1, {payload!r})\nthreading.Event().wait()\n",
    )

    assert result.returncode == exit_code, result.stdout + result.stderr
    assert result.stdout == prefix + summary
    assert "timed out" not in result.stderr


@pytest.mark.parametrize("output", ["", "unfinished progress"])
def test_watchdog_times_out_without_a_summary(tmp_path: Path, output: str) -> None:
    """Incomplete output must not block the watchdog's deadline."""
    result = _run_scripted_pytest(
        tmp_path,
        f"import os, threading\nos.write(1, {output.encode()!r})\n"
        "threading.Event().wait()\n",
    )

    assert result.returncode == 124, result.stdout + result.stderr
    assert result.stdout == output
    assert "pytest timed out after 2s" in result.stderr


def test_watchdog_preserves_child_exit_and_final_output(tmp_path: Path) -> None:
    """Drain output at EOF without replacing a genuine pytest failure status."""
    result = _run_scripted_pytest(
        tmp_path,
        "import os\nos.write(1, 'failure: café'.encode())\nraise SystemExit(3)\n",
    )

    assert result.returncode == 3
    assert result.stdout == "failure: café"


def test_run_pytest_wrapper_exits_after_summary(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    test_file = tmp_path / "test_wrapper_smoke.py"
    test_file.write_text(
        "def test_wrapper_smoke():\n    assert True\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "run_pytest.py"),
            str(test_file),
            "-q",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTEST_TIMEOUT": "10",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
