#!/usr/bin/env python3
"""Inspect or replay audited AI Trust inputs without starting Moonwalker."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import aiosqlite  # noqa: E402
import httpx  # noqa: E402
from service.ai_trust_comparison import (  # noqa: E402
    MAX_ATTEMPTS,
    MAX_EXPERIMENT_ATTEMPTS,
    MAX_ROWS,
    ComparisonError,
    database_samples,
    load_samples,
    run_comparison,
)


def parser() -> argparse.ArgumentParser:
    """Describe the offline entry points and explicit inference opt-in."""
    result = argparse.ArgumentParser(description=__doc__)
    source = result.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Audited JSONL input")
    source.add_argument(
        "--database", type=Path, help="Read-only Moonwalker SQLite file"
    )
    result.add_argument(
        "--output", type=Path, required=True, help="Separate new run directory"
    )
    result.add_argument("--baseline-model", default="baseline-unconfigured")
    result.add_argument("--clef-model", default="clef:latest")
    result.add_argument("--flash-model", default="clef-flash:latest")
    result.add_argument("--base-url", default="http://localhost:11434")
    result.add_argument(
        "--limit", type=int, default=MAX_ROWS, help="Maximum input rows (1..10000)"
    )
    result.add_argument(
        "--attempt-budget",
        type=int,
        default=MAX_ATTEMPTS,
        help="Inference attempts per run (default 30, maximum 3000); explicitly increase for larger evaluations",
    )
    result.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly allow inference within the selected attempt budget",
    )
    result.add_argument(
        "--resume",
        action="store_true",
        help="Resume exactly the same run without resetting its budget",
    )
    return result


async def main() -> int:
    """Validate source/options, execute the isolated workflow and print its summary."""
    args = parser().parse_args()
    # This standalone process reuses the chat parser but never logs raw responses.
    logging.disable(logging.DEBUG)
    if not 1 <= args.limit <= MAX_ROWS:
        parser().error("--limit must be between 1 and 10000")
    if args.execute and args.baseline_model == "baseline-unconfigured":
        parser().error("--execute requires an explicit --baseline-model")
    if not 1 <= args.attempt_budget <= MAX_EXPERIMENT_ATTEMPTS:
        parser().error("--attempt-budget must be between 1 and 3000")
    source = (args.input or args.database).resolve()
    output = args.output.resolve()
    if source == output or source.is_relative_to(output):
        parser().error("input/database must be outside the output directory")
    try:
        samples = (
            await database_samples(source, args.limit)
            if args.database
            else await asyncio.to_thread(load_samples, source, args.limit)
        )
        report = await run_comparison(
            samples,
            output,
            args.base_url,
            [args.baseline_model, args.clef_model, args.flash_model],
            execute=args.execute,
            resume=args.resume,
            attempt_budget=args.attempt_budget,
        )
    except (
        ComparisonError,
        OSError,
        aiosqlite.Error,
        httpx.HTTPError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print("Comparison failed: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print(
            "Interrupted; completed results and consumed attempts are retained.",
            file=sys.stderr,
        )
        raise SystemExit(130) from None
