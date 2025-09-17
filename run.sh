#!/usr/bin/env bash
set -e

echo "📂 Copying config..."
rm -rf backend/config.ini
rm -rf frontend/src/config.ts
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

echo "🐍 Installing Python deps & starting Quart..."
cd backend
pip install -r requirements.txt
python app.py