#!/usr/bin/env bash
set -e

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

print_node_runtime_help() {
    echo "Moonwalker uses the Node.js version pinned in .nvmrc."
    echo
    echo "macOS or Linux with nvm (recommended):"
    echo "  Install nvm: https://github.com/nvm-sh/nvm#installing-and-updating"
    echo "  nvm install"
    echo "  nvm use"
    echo "  ./run.sh start"
    echo
    echo "macOS with Homebrew:"
    echo "  brew install node@24"
    echo '  export PATH="$(brew --prefix node@24)/bin:$PATH"'
    echo "  ./run.sh start"
}

check_frontend_runtime() {
    local node_major
    local node_minor
    local node_version
    local npm_major
    local npm_version

    if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
        echo "❌ Node.js 24 and npm 11 are required but were not both found."
        print_node_runtime_help
        return 1
    fi

    node_version="$(node -p 'process.versions.node')"
    npm_version="$(npm --version)"
    IFS=. read -r node_major node_minor _ <<< "$node_version"
    IFS=. read -r npm_major _ <<< "$npm_version"

    if [ "$node_major" -ne 24 ] || [ "$node_minor" -lt 11 ] || [ "$npm_major" -ne 11 ]; then
        echo "❌ Unsupported frontend runtime: Node.js v${node_version}, npm ${npm_version}."
        echo "   Required: Node.js >=24.11.0 <25 and npm >=11 <12."
        print_node_runtime_help
        return 1
    fi
}

service_process_is_running() {
    local pid

    [ -f "$PID_FILE" ] || return 1
    while read -r pid; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    done < "$PID_FILE"
    return 1
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
    local active_target=""
    local app_pid
    local release_venv
    # Check if services are already running
    if [ -f "$LOCK_FILE" ]; then
        if service_process_is_running; then
            echo "❌ Services are already running"
            exit 1
        fi

        echo "⚠️  Removing stale service lock from an incomplete startup."
        rm -f "$LOCK_FILE" "$PID_FILE"
    fi

    check_frontend_runtime

    echo "📦 Installing frontend deps & building Vue..."
    cd frontend
    npm ci --ignore-scripts
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

    echo "🐍 Building a verified Python environment..."
    if [ "$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.14" ]; then
        echo "❌ Python 3.14 is required. See .python-version."
        exit 1
    fi
    if [ -L .venv ]; then
        active_target="$(readlink .venv)"
    fi
    if [ "$(basename "$active_target")" = "slot-a" ]; then
        release_venv=".venvs/slot-b"
    else
        release_venv=".venvs/slot-a"
    fi
    mkdir -p .venvs
    rm -rf "$release_venv" .venv.next
    python3 -m venv "$release_venv"
    ./scripts/install_python_dependencies.sh \
        "$release_venv/bin/python" \
        backend/requirements.txt
    "$release_venv/bin/python" -m pip check
    PYTHONPATH=backend "$release_venv/bin/python" -c "from controller import route_handlers"

    rm -rf .venv.previous
    if [ -e .venv ] || [ -L .venv ]; then
        mv .venv .venv.previous
    fi
    ln -s "$release_venv" .venv.next
    if ! mv .venv.next .venv; then
        if [ -e .venv.previous ] || [ -L .venv.previous ]; then
            mv .venv.previous .venv
        fi
        exit 1
    fi

    # Do not mark the service as running until all build and validation work
    # has succeeded. EXIT/interrupt cleanup protects the short launch window.
    touch "$LOCK_FILE"
    trap 'rm -f "$LOCK_FILE" "$PID_FILE"' EXIT INT TERM

    echo "🚀 Starting Litestar..."
    cd backend
    if [ "$trace" = "true" ]; then
        MOONWALKER_LOG_LEVEL=TRACE MOONWALKER_PORT="$port" ../.venv/bin/python app.py > ../run.log 2>&1 &
    elif [ "$debug" = "true" ]; then
        MOONWALKER_DEBUG=True MOONWALKER_PORT="$port" ../.venv/bin/python app.py > ../run.log 2>&1 &
    else
        MOONWALKER_PORT="$port" ../.venv/bin/python app.py > ../run.log 2>&1 &
    fi
    app_pid=$!
    echo "$app_pid" > ../$PID_FILE
    cd ..

    sleep 1
    if ! kill -0 "$app_pid" 2>/dev/null; then
        echo "❌ Backend exited during startup. See run.log for details."
        rm -f "$PID_FILE" "$LOCK_FILE"
        exit 1
    fi

    trap - EXIT INT TERM
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
