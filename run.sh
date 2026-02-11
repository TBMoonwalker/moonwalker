#!/usr/bin/env bash
set -e

FRONTEND_CONFIG=frontend/src/config.ts
PID_FILE="moonwalker.pid"
LOCK_FILE="moonwalker.lock"

usage() {
    echo "Usage: $0 {start|stop} [-d|--debug] [-p|--port PORT]"
}

build_frontend_with_fallback() {
    local first_status=0
    local second_status=0

    echo "🏗️  Building frontend (standard)..."
    if npm run build-only; then
        return 0
    fi
    first_status=$?
    echo "⚠️  Standard frontend build failed (exit ${first_status})."

    echo "🏗️  Retrying frontend build with constrained Node heap (1536 MB)..."
    if NODE_OPTIONS="--max-old-space-size=1536" npm run build-only; then
        return 0
    fi
    second_status=$?
    echo "⚠️  Heap-constrained build failed (exit ${second_status})."

    echo "🏗️  Retrying frontend build in low-memory mode (no minify, 1024 MB heap)..."
    if NODE_OPTIONS="--max-old-space-size=1024" npx vite build --minify=false; then
        return 0
    fi

    echo "❌ Frontend build failed after fallback attempts."
    return ${second_status}
}

# Function to stop all services
stop_services() {

    if [ -z "${MOONWALKER_DEBUG}" ]; then
        unset MOONWALKER_DEBUG
    fi
    if [ -f "$LOCK_FILE" ]; then
        echo "🛑 Stopping services..."
        if [ -f "$PID_FILE" ]; then
            while read -r pid; do
                if kill -9 "$pid" 2>/dev/null; then
                    kill "$pid"
                    echo "Stopped process with PID: $pid"
                fi
            done < "$PID_FILE"
            rm "$PID_FILE"
        fi
        rm "$LOCK_FILE"
        echo "✅ All services stopped"
    else
        echo "⚠️  No running services found or services not started by this script"
    fi
}

# Function to start all services
start_services() {
    local debug="${1:-false}"
    local port="${2:-8130}"
    # Check if services are already running
    if [ -f "$LOCK_FILE" ]; then
        echo "❌ Services are already running"
        exit 1
    fi

    # Create lock file to indicate services are running
    touch "$LOCK_FILE"

    echo "📂 Copying config..."
    if [ -f "$FRONTEND_CONFIG" ]; then
        rm "$FRONTEND_CONFIG"
    fi
    cp config.ts frontend/src/

    echo "📦 Checking npm-run-all..."
    if ! npx --no-install run-p --version >/dev/null 2>&1; then
      echo "⬇️  Installing npm-run-all..."
      cd frontend
      npm install --save-dev npm-run-all
      cd ..
    fi

    echo "📦 Installing frontend deps & building Vue..."
    cd frontend
    npm install
    # Startup path should prioritize successful asset build over type-checking.
    # Type checks are still available via `npm run build`/CI.
    build_frontend_with_fallback
    cd ..

    echo "📂 Copying assets into backend..."
    rm -rf backend/static/* backend/templates/*
    cp -r frontend/dist/assets backend/static/
    cp frontend/dist/index.html backend/templates/

    echo "🐍 Installing Python venv and deps & starting Quart..."
    python3 -m venv .venv
    cd backend
    ../.venv/bin/pip install -r requirements.txt
    if [ "$debug" = "true" ]; then
        MOONWALKER_DEBUG=True MOONWALKER_PORT="$port" ../.venv/bin/python app.py > ../run.log 2>&1 &
    else
        MOONWALKER_PORT="$port" ../.venv/bin/python app.py > ../run.log 2>&1 &
    fi
    echo $! > ../$PID_FILE
    cd ..

    echo "✅ Services started in background. Use './run.sh stop' to stop them."
}

# Main script logic
cmd=""
debug=false
port=8130

while [ $# -gt 0 ]; do
    case "$1" in
        start|stop)
            if [ -n "$cmd" ]; then
                echo "❌ Multiple commands specified."
                usage
                exit 1
            fi
            cmd="$1"
            shift
            ;;
        -d|--debug)
            debug=true
            shift
            ;;
        -p|--port)
            if [ -z "$2" ]; then
                echo "❌ Missing port value for $1"
                usage
                exit 1
            fi
            if ! [[ "$2" =~ ^[0-9]+$ ]] || [ "$2" -lt 1 ] || [ "$2" -gt 65535 ]; then
                echo "❌ Invalid port: $2 (expected 1-65535)"
                exit 1
            fi
            port="$2"
            shift 2
            ;;
        --port=*)
            port_value="${1#*=}"
            if ! [[ "$port_value" =~ ^[0-9]+$ ]] || [ "$port_value" -lt 1 ] || [ "$port_value" -gt 65535 ]; then
                echo "❌ Invalid port: $port_value (expected 1-65535)"
                exit 1
            fi
            port="$port_value"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "❌ Unknown argument: $1"
            usage
            exit 1
            ;;
    esac
done

case "$cmd" in
    start)
        start_services "$debug" "$port"
        ;;
    stop)
        stop_services
        ;;
    *)
        usage
        exit 1
        ;;
esac
