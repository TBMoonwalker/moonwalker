#!/usr/bin/env bash
set -e

FRONTEND_CONFIG=frontend/src/config.ts
PID_FILE="moonwalker.pid"
LOCK_FILE="moonwalker.lock"

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
    # Set Debug Logging
    if [ $# -eq 2 && $2 eq "DEBUG"]; then
        export MOONWALKER_DEBUG=True
    fi

    # Check if services are already running
    if [ -f "$LOCK_FILE" ]; then
        echo "❌ Services are already running"
        exit 1
    fi

    # Create lock file to indicate services are running
    touch "$LOCK_FILE"

    echo "📂 Copying config..."
    if [ -f "$FRONTEND_FILE" ]; then
        rm frontend/src/config.ts
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
    npm run build
    cd ..

    echo "📂 Copying assets into backend..."
    rm -rf backend/static/* backend/templates/*
    cp -r frontend/dist/assets backend/static/
    cp frontend/dist/index.html backend/templates/

    echo "🐍 Installing Python venv and deps & starting Quart..."
    python3 -m venv .venv
    cd backend
    ../.venv/bin/pip install -r requirements.txt
    MOONWALKER_DEBUG=True ../.venv/bin/python app.py > ../run.log 2>&1 &
    echo $! > ../$PID_FILE
    cd ..

    echo "✅ Services started in background. Use './run.sh stop' to stop them."
}

# Main script logic
case "$1" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    *)
        echo "Usage: $0 {start|stop} (debug)"
        exit 1
        ;;
esac