"""CLI integration proving read-only operation and explicit inference opt-in."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from test_ai_trust_comparison import NAMES, answer_body, sample

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "compare_ai_trust.py"


def test_database_dry_run_keeps_operational_state_unchanged(tmp_path: Path) -> None:
    database = tmp_path / "live.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE ai_trust_predictions (id INTEGER,deal_id TEXT,feature_bundle_json TEXT,outcome_status TEXT,outcome_profit REAL,outcome_duration_hours REAL,outcome_so_count INTEGER)"
        )
        connection.execute(
            "INSERT INTO ai_trust_predictions VALUES (1,'deal','{}','closed',1,24,0)"
        )
        connection.execute("CREATE TABLE app_config (value TEXT)")
        connection.execute("INSERT INTO app_config VALUES ('unchanged')")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    output = tmp_path / "run"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--database",
            str(database),
            "--output",
            str(output),
            "--base-url",
            "http://127.0.0.1:1",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["attempts"] == 0 and report["status"] == "insufficient_data"
    assert report["execute"] is False
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert not (output / "results.jsonl").exists()
    resumed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--database",
            str(database),
            "--output",
            str(output),
            "--base-url",
            "http://127.0.0.1:1",
            "--resume",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert resumed.returncode == 0
    assert json.loads(resumed.stdout) == report


def test_cli_execute_needs_explicit_baseline_and_safe_output(tmp_path: Path) -> None:
    source = tmp_path / "inputs.jsonl"
    source.write_text("{}\n")
    args = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(source),
        "--output",
        str(tmp_path / "run"),
    ]
    execute = subprocess.run(
        [*args, "--execute"], capture_output=True, text=True, timeout=15
    )
    assert execute.returncode == 2 and "explicit --baseline-model" in execute.stderr
    unsafe = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(source),
            "--output",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert unsafe.returncode == 2 and "outside the output" in unsafe.stderr
    assert source.read_text() == "{}\n"


def test_corrupt_or_oversized_input_fails_without_network(tmp_path: Path) -> None:
    source = tmp_path / "inputs.jsonl"
    for text in ("not-json\n", "x" * 65537):
        source.write_text(text)
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input",
                str(source),
                "--output",
                str(tmp_path / "run"),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 2 and "Comparison failed" in result.stderr
        assert not (tmp_path / "run").exists()


def test_execute_cli_against_fixture_server_and_resume(tmp_path: Path) -> None:
    """Exercise real CLI/HTTP/journal wiring against fixtures, not real models."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def do_GET(self) -> None:
            body = (
                {"version": "0.35.1"}
                if self.path == "/api/version"
                else {
                    "models": [
                        {"name": name, "digest": "fixture-digest-" + name}
                        for name in NAMES
                    ]
                }
            )
            self.respond(body)

        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, payload))
            if self.path == "/api/chat":
                body = {
                    "message": {
                        "content": '{"risk_score":25,"confidence":0.5,"would_warn":false,"warning_severity":"none","reason_codes":[],"operator_note":"Normal"}'
                    }
                }
            else:
                body = answer_body()
                body["model"] = payload["model"]
            self.respond(body)

        def respond(self, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    source = tmp_path / "audited.jsonl"
    source.write_text("".join(json.dumps(sample(i)) + "\n" for i in range(4)))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    args = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(source),
        "--output",
        str(tmp_path / "run"),
        "--execute",
        "--baseline-model",
        NAMES[0],
        "--base-url",
        f"http://127.0.0.1:{server.server_port}",
    ]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["attempts"] == len(requests) == 12
        assert report["status"] == "feasibility_only"
        assert report["paired_cohort_ids"] == {
            "tuning": ["0", "1"],
            "evaluation": ["2", "3"],
        }
        assert all("outcome" not in json.dumps(payload) for _, payload in requests)
        assert sum(path == "/v1/systemone" for path, _ in requests) == 8
        resumed = subprocess.run(
            [*args, "--resume"], capture_output=True, text=True, timeout=15
        )
        assert resumed.returncode == 0, resumed.stderr
        assert json.loads(resumed.stdout) == report
        assert len(requests) == 12
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
