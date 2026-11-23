#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PIP_TOOLS_VERSION="7.6.2"
cd "$ROOT_DIR/backend"

compile_lock() {
    local input_file="$1"
    local output_file="$2"

    uvx --from "pip-tools==${PIP_TOOLS_VERSION}" pip-compile \
        --allow-unsafe \
        --generate-hashes \
        --no-emit-index-url \
        --no-emit-trusted-host \
        --resolver=backtracking \
        --strip-extras \
        --output-file "$output_file" \
        "$input_file"
}

compile_lock \
    "requirements.in" \
    "requirements.txt"
compile_lock \
    "requirements-dev.in" \
    "requirements-dev.txt"

# The lock gate needs the `packaging` module. Run it through uv (already a
# dependency of this script via uvx) instead of the host's system python3,
# which may not have packaging installed. Use the freshly regenerated dev
# lock's own pin so this gate always validates with the same packaging
# version the venv (and the CI gate) uses, never a stale hardcoded copy.
PACKAGING_VERSION="$(
    awk -F'==' '/^packaging==/ { v = $2; sub(/[; ].*$/, "", v); print v; exit }' \
        "$ROOT_DIR/backend/requirements-dev.txt"
)"
if [ -z "$PACKAGING_VERSION" ]; then
    echo "ERROR: no packaging pin found in backend/requirements-dev.txt" >&2
    exit 1
fi
uv run --no-project --with "packaging==${PACKAGING_VERSION}" python \
    "$ROOT_DIR/scripts/check_dependency_locks.py"
