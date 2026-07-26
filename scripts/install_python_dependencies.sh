#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 PYTHON_BIN REQUIREMENTS_LOCK" >&2
    exit 2
fi

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$1"
REQUIREMENTS_LOCK="$2"
PYAE_WHEEL="$ROOT_DIR/backend/vendor/pyaes-1.6.1-py3-none-any.whl"
PYAE_SHA256="97e69519924dde9254b26b20fe37eebb4a6b811d6bda4945a53fba04a4188a83"
HASH_SCRIPT="import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())"

actual_hash="$("$PYTHON_BIN" -c "$HASH_SCRIPT" "$PYAE_WHEEL")"
if [ "$actual_hash" != "$PYAE_SHA256" ]; then
    echo "ERROR: vendored pyaes wheel failed SHA-256 verification" >&2
    exit 1
fi

# Telethon requires pyaes 1.6.1, for which PyPI publishes only a source
# distribution. Install the reviewed local pure-Python wheel first so pip never
# executes its setup.py during CI or startup.
"$PYTHON_BIN" -m pip install \
    --force-reinstall \
    --no-deps \
    --no-index \
    "$PYAE_WHEEL"
"$PYTHON_BIN" -m pip install \
    --only-binary=:all: \
    --require-hashes \
    -r "$REQUIREMENTS_LOCK"
