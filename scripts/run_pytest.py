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


def main() -> int:
    timeout_seconds = int(os.getenv("PYTEST_TIMEOUT", "300"))
    post_summary_timeout = int(
        os.getenv("PYTEST_POST_SUMMARY_TIMEOUT", os.getenv("PYTEST_IDLE_TIMEOUT", "5"))
    )
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

    while True:
        now = time.monotonic()
        if now - start > timeout_seconds:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            print(f"pytest timed out after {timeout_seconds}s", file=sys.stderr)
            return 124

        events = selector.select(timeout=0.1)
        for key, _ in events:
            line = key.fileobj.readline()
            if not line:
                selector.unregister(key.fileobj)
                continue
            last_output = time.monotonic()
            sys.stdout.write(line)
            sys.stdout.flush()
            if SUMMARY_RE.search(line):
                summary_seen_at = time.monotonic()
                summary_line = line.strip()

        if summary_seen_at is not None and proc.poll() is None:
            if time.monotonic() - last_output > post_summary_timeout:
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

    remaining_output = proc.stdout.read() if proc.stdout is not None else ""
    if remaining_output:
        sys.stdout.write(remaining_output)
        sys.stdout.flush()
    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
