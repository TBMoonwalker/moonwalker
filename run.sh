#!/usr/bin/env bash
set -e

FRONTEND_CONFIG=frontend/src/config.ts
PID_FILE="moonwalker.pid"
LOCK_FILE="moonwalker.lock"

usage() {
    echo "Usage: $0 {start|stop} [-d|--debug] [-t|--trace] [-p|--port PORT]"
}

build_frontend_with_fallback() {
    local status=0

    echo "🏗️  Building frontend (standard)..."
    if npm run build-only; then
        return 0
    else
        status=$?
    fi
    echo "⚠️  Standard frontend build failed (exit ${status})."

    echo "🏗️  Retrying frontend build with constrained Node heap (1280 MB)..."
    if NODE_OPTIONS="--max-old-space-size=1280" npm run build-only; then
        return 0
    else
        status=$?
    fi
    echo "⚠️  Heap-constrained build failed (exit ${status})."

    echo "🏗️  Retrying frontend build in low-memory mode (no minify, no manual chunks, 1024 MB heap)..."
    if MOONWALKER_LOW_MEMORY_BUILD=1 NODE_OPTIONS="--max-old-space-size=1024" npm run build-only; then
        return 0
    else
        status=$?
    fi

    echo "❌ Frontend build failed after fallback attempts (last exit ${status})."
    return ${status}
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
    local trace="${2:-false}"
    local port="${3:-8130}"
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

    if [ ! -d frontend/dist/assets ] || [ ! -f frontend/dist/index.html ]; then
        echo "❌ Frontend build artifacts missing. Aborting startup."
        rm -f "$LOCK_FILE"
        exit 1
    fi

    echo "📂 Copying assets into backend..."
    rm -rf backend/static/* backend/templates/*
    cp -r frontend/dist/assets backend/static/
    cp frontend/dist/index.html backend/templates/

    echo "🐍 Installing Python venv and deps & starting Litestar..."
    python3 -m venv .venv
    cd backend
    ../.venv/bin/pip install -r requirements.txt
    if [ "$trace" = "true" ]; then
        MOONWALKER_LOG_LEVEL=TRACE MOONWALKER_PORT="$port" ../.venv/bin/python app.py > ../run.log 2>&1 &
    elif [ "$debug" = "true" ]; then
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
trace=false
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
        -t|--trace)
            trace=true
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
        start_services "$debug" "$trace" "$port"
        ;;
    stop)
        stop_services
        ;;
    *)
        usage
        exit 1
        ;;
esac
