#!/usr/bin/env python3
"""Run pytest with a watchdog to avoid hanging after completion."""

from __future__ import annotations

import codecs
import locale
import os
import re
import selectors
import subprocess
import sys
import time

SUMMARY_RE = re.compile(r"=+ .* in .*s(?: \([\d:]+\))? =+")


def main() -> int:
    """Forward pytest output while enforcing execution and shutdown deadlines."""
    timeout_seconds = int(os.getenv("PYTEST_TIMEOUT", "300"))
    post_summary_timeout = int(
        os.getenv("PYTEST_POST_SUMMARY_TIMEOUT", os.getenv("PYTEST_IDLE_TIMEOUT", "5"))
    )
    args = [sys.executable, "-m", "pytest", *sys.argv[1:]]

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )

    selector = selectors.DefaultSelector()
    assert proc.stdout is not None
    selector.register(proc.stdout, selectors.EVENT_READ)
    decoder = codecs.getincrementaldecoder(locale.getpreferredencoding(False))()
    pending_line = ""

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
                proc.wait()
            selector.close()
            proc.stdout.close()
            print(f"pytest timed out after {timeout_seconds}s", file=sys.stderr)
            return 124

        events = selector.select(timeout=0.1)
        for key, _ in events:
            # TextIOWrapper.readline() can both block on partial lines and hide
            # prefetched lines from the selector after the OS pipe is drained.
            chunk = os.read(key.fd, 65536)
            output = decoder.decode(chunk, final=not chunk)
            if not chunk:
                selector.unregister(key.fileobj)
            else:
                last_output = time.monotonic()
            sys.stdout.write(output)
            sys.stdout.flush()
            pending_line += output
            lines = pending_line.split("\n")
            pending_line = lines.pop()
            if not chunk and pending_line:
                lines.append(pending_line)
                pending_line = ""
            for line in lines:
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
                    proc.wait()
                selector.close()
                proc.stdout.close()
                if summary_line and (
                    "failed" in summary_line or "error" in summary_line
                ):
                    return 1
                return 0

        if proc.poll() is not None and not selector.get_map():
            break

    selector.close()
    proc.stdout.close()
    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
