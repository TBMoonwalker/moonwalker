#!/usr/bin/env python3
"""Verify that a staged frontend entrypoint references only present assets.

Stdlib-only by contract: ``run.sh`` invokes this with the bootstrap python
before the project virtualenv exists, so it must not import the application
stack. Run with ``PYTHONPATH=backend`` so ``staging_check`` resolves.
"""

import sys
from pathlib import Path

from staging_check import missing_referenced_assets


def main() -> int:
    """Exit 0 when the stage is complete, 1 on a partial stage, 2 on bad usage."""
    if len(sys.argv) != 3:
        print(
            "usage: verify_frontend_staging.py <index.html> <static root>",
            file=sys.stderr,
        )
        return 2

    index_file = Path(sys.argv[1])
    static_root = Path(sys.argv[2])
    if not index_file.is_file():
        print(f"missing staged entrypoint: {index_file}", file=sys.stderr)
        return 1

    missing = missing_referenced_assets(index_file, static_root)
    for reference in missing:
        print(f"missing staged asset: {reference}", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
