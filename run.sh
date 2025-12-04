#!/usr/bin/env bash
set -e

BACKEND_CONFIG=backend/config.ini
FRONTEND_CONFIG=frontend/src/config.ts

echo "📂 Copying config..."
if [ -f "$BACKEND_FILE" ]; then
    rm backend/config.ini
fi
if [ -f "$FRONTEND_FILE" ]; then
    rm frontend/src/config.ts
fi
cp config.ini backend/
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
nohup ../.venv/bin/python app.py > ../run.log 2>&1 &