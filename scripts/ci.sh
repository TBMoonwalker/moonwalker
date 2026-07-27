#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
FAILURES=0
RESULTS=()

if ! command -v npm >/dev/null 2>&1; then
    cat >&2 <<'EOF'
ERROR: npm is required but was not found on PATH.
Moonwalker development requires Node.js 24 and npm 11.

With nvm:
  nvm install
  nvm use

With Homebrew on macOS:
  brew install node@24
  export PATH="$(brew --prefix node@24)/bin:$PATH"
EOF
    exit 127
fi

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
BACKEND_COVERAGE_JSON="/tmp/moonwalker-backend-coverage.json"
run_step "Backend tests + coverage (pytest)" env \
    MOONWALKER_DB_URL=sqlite:////tmp/moonwalker-test.sqlite \
    PYTEST_ASYNCIO_MODE=auto \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    "$PYTHON_BIN" "$ROOT_DIR/scripts/run_pytest.py" \
    -p pytest_asyncio.plugin \
    -p pytest_cov.plugin \
    --cov-branch \
    --cov="$ROOT_DIR/backend" \
    --cov-report="term:skip-covered" \
    --cov-report="json:$BACKEND_COVERAGE_JSON" \
    "$ROOT_DIR/backend/tests"
run_step "Backend coverage ratchet" \
    "$PYTHON_BIN" \
    "$ROOT_DIR/scripts/check_coverage_thresholds.py" \
    "$BACKEND_COVERAGE_JSON"
run_step "Frontend type check (vue-tsc)" npm --prefix "$ROOT_DIR/frontend" run type-check
run_step "Frontend legacy + rendered tests" npm --prefix "$ROOT_DIR/frontend" run test
run_step "Frontend coverage ratchet" npm --prefix "$ROOT_DIR/frontend" run test:coverage
run_step "Frontend build (vite)" npm --prefix "$ROOT_DIR/frontend" run build-only
if [ "${MOONWALKER_RUN_E2E:-0}" = "1" ]; then
    run_step "Frontend dry-run E2E (Playwright)" \
        npm --prefix "$ROOT_DIR/frontend" run test:e2e
else
    RESULTS+=("SKIP: Frontend dry-run E2E (set MOONWALKER_RUN_E2E=1)")
fi
run_step "Python dependency audit" \
    "$PYTHON_BIN" -m pip_audit \
    --disable-pip \
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
