#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

"$ROOT_DIR/scripts/check_dependency_locks.py"
"$PYTHON_BIN" -m pip check
"$PYTHON_BIN" -m pip_audit \
    --disable-pip \
    --progress-spinner off \
    --strict \
    --requirement "$ROOT_DIR/backend/requirements-dev.txt"
npm --prefix "$ROOT_DIR/frontend" audit --audit-level=high
npm --prefix "$ROOT_DIR/frontend" audit signatures
