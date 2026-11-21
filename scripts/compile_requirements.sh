#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PIP_TOOLS_VERSION="7.6.2"
PACKAGING_VERSION="26.3"
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
# which may not have packaging installed. Pinned to the dev-lock version.
uv run --no-project --with "packaging==${PACKAGING_VERSION}" python \
    "$ROOT_DIR/scripts/check_dependency_locks.py"
