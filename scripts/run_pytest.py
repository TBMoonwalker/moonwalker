#!/usr/bin/env python3
"""Run pytest with a watchdog to avoid hanging after completion."""

from __future__ import annotations

import os
import re
import selectors
import subprocess
import sys
import time

SUMMARY_RE = re.compile(r"=+ .* in .*s =+")
FAILURE_RE = re.compile(r"\bFAILED\b|\bERROR\b")


def main() -> int:
    timeout_seconds = int(os.getenv("PYTEST_TIMEOUT", "60"))
    idle_timeout = int(os.getenv("PYTEST_IDLE_TIMEOUT", "5"))
    args = [sys.executable, "-m", "pytest", *sys.argv[1:]]

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    selector = selectors.DefaultSelector()
    assert proc.stdout is not None
    selector.register(proc.stdout, selectors.EVENT_READ)

    start = time.monotonic()
    last_output = time.monotonic()
    summary_seen_at: float | None = None
    summary_line: str | None = None
    saw_failure = False

    while True:
        if proc.poll() is not None and summary_seen_at is None:
            break

        now = time.monotonic()
        if now - start > timeout_seconds:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            print(f"pytest timed out after {timeout_seconds}s", file=sys.stderr)
            return 124

        if now - last_output > idle_timeout and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            return 1 if saw_failure else 0

        events = selector.select(timeout=0.1)
        for key, _ in events:
            line = key.fileobj.readline()
            if not line:
                continue
            last_output = time.monotonic()
            sys.stdout.write(line)
            sys.stdout.flush()
            if FAILURE_RE.search(line):
                saw_failure = True
            if SUMMARY_RE.search(line):
                summary_seen_at = time.monotonic()
                summary_line = line.strip()

        if summary_seen_at is not None and proc.poll() is None:
            if time.monotonic() - summary_seen_at > 1:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                if summary_line and ("failed" in summary_line or "error" in summary_line):
                    return 1
                return 0

        if proc.poll() is not None and not events:
            break

    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
