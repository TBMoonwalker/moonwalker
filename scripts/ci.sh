#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
FAILURES=0
RESULTS=()

if [ ! -x "$PYTHON_BIN" ]; then
    python3 -m venv "$VENV_DIR"
fi

"$ROOT_DIR/scripts/install_python_dependencies.sh" \
    "$PYTHON_BIN" \
    "$ROOT_DIR/backend/requirements-dev.txt"
"$PYTHON_BIN" -m pip check

npm --prefix "$ROOT_DIR/frontend" ci --ignore-scripts

run_step() {
    local name="$1"
    shift
    "$@"
    local status=$?
    if [ $status -eq 0 ]; then
        RESULTS+=("PASS: ${name}")
    else
        RESULTS+=("FAIL: ${name}")
        FAILURES=$((FAILURES + 1))
    fi
    return 0
}

set +e
run_step "Backend format (black --check)" "$PYTHON_BIN" -m black --check "$ROOT_DIR/backend"
run_step "Backend lint (ruff)" "$PYTHON_BIN" -m ruff check "$ROOT_DIR/backend"
run_step "Backend import sort (isort --check-only)" "$PYTHON_BIN" -m isort --profile black --check-only "$ROOT_DIR/backend"
run_step "Backend type check (mypy)" env MYPYPATH="$ROOT_DIR/backend" "$PYTHON_BIN" -m mypy --config-file "$ROOT_DIR/mypy.ini" "$ROOT_DIR/backend"
run_step "Guardrail: strategy/indicator + commented blocks" "$PYTHON_BIN" "$ROOT_DIR/scripts/check_backend_guardrails.py"
run_step "Dependency lock policy" "$PYTHON_BIN" "$ROOT_DIR/scripts/check_dependency_locks.py"
run_step "Backend tests (pytest)" env \
    MOONWALKER_DB_URL=sqlite:////tmp/moonwalker-test.sqlite \
    PYTEST_ASYNCIO_MODE=auto \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    "$PYTHON_BIN" "$ROOT_DIR/scripts/run_pytest.py" -p pytest_asyncio.plugin "$ROOT_DIR/backend/tests"
run_step "Frontend type check (vue-tsc)" npm --prefix "$ROOT_DIR/frontend" run type-check
run_step "Frontend tests (node --test)" npm --prefix "$ROOT_DIR/frontend" run test
run_step "Frontend build (vite)" npm --prefix "$ROOT_DIR/frontend" run build-only
# CCXT 4.5.67 hard-pins setuptools 82.0.1. PYSEC-2026-3447 only affects
# building source distributions; CI installs wheels exclusively.
run_step "Python dependency audit" \
    "$PYTHON_BIN" -m pip_audit \
    --disable-pip \
    --ignore-vuln PYSEC-2026-3447 \
    --progress-spinner off \
    --strict \
    --requirement "$ROOT_DIR/backend/requirements-dev.txt"
run_step "npm vulnerability audit" npm --prefix "$ROOT_DIR/frontend" audit --audit-level=high
run_step "npm registry signatures" npm --prefix "$ROOT_DIR/frontend" audit signatures
set -e

echo "-----"
echo "CI Summary"
for line in "${RESULTS[@]}"; do
    echo "$line"
done
echo "-----"

if [ $FAILURES -gt 0 ]; then
    echo "${FAILURES} check(s) failed."
    exit 1
fi

echo "All checks passed."
exit 0
