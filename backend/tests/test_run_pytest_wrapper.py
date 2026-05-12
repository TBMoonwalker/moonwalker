import os
import subprocess
import sys
from pathlib import Path


def test_run_pytest_wrapper_exits_after_summary(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    test_file = tmp_path / "test_wrapper_smoke.py"
    test_file.write_text(
        "def test_wrapper_smoke():\n" "    assert True\n",
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
