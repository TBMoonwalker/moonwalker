#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

if [ "${CI_CHECK_FRONTEND_UNUSED_EXPORTS:-0}" != "1" ]; then
    echo "Skipping optional frontend unused export check (set CI_CHECK_FRONTEND_UNUSED_EXPORTS=1 to enable)."
    exit 0
fi

if [ ! -d "$FRONTEND_DIR" ]; then
    echo "Frontend directory not found: $FRONTEND_DIR"
    exit 1
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "frontend/node_modules missing. Install dependencies first."
    exit 1
fi

if [ -x "$FRONTEND_DIR/node_modules/.bin/ts-prune" ]; then
    cd "$FRONTEND_DIR"
    node_modules/.bin/ts-prune -p tsconfig.app.json
    exit 0
fi

echo "CI_CHECK_FRONTEND_UNUSED_EXPORTS=1 is set, but ts-prune is not installed."
echo "Add ts-prune as a frontend devDependency to enable this check."
exit 1
