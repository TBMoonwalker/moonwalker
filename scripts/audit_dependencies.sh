#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

# The gate and the audit steps need the dev lock's tools; fail before the
# first step with a clear message when the selected interpreter is a
# runtime-only environment.
if ! "$PYTHON_BIN" -c "import packaging, pip_audit" 2>/dev/null; then
    echo "ERROR: $PYTHON_BIN is missing the dev tools (packaging, pip_audit)." >&2
    echo "Install the development lock first; see AGENTS.md (Backend)." >&2
    exit 1
fi

"$PYTHON_BIN" "$ROOT_DIR/scripts/check_dependency_locks.py"
"$PYTHON_BIN" -m pip check
"$PYTHON_BIN" -m pip_audit \
    --disable-pip \
    --progress-spinner off \
    --strict \
    --requirement "$ROOT_DIR/backend/requirements-dev.txt"
npm --prefix "$ROOT_DIR/frontend" audit --audit-level=high
npm --prefix "$ROOT_DIR/frontend" audit signatures
