#!/usr/bin/env bash
# Starts the Empira API (port 8000) and the web app (port 8501). Ctrl+C stops both.
# Needs: pip install -r requirements.txt -r app/requirements.txt
set -e
cd "$(dirname "$0")/.."
python -m uvicorn app.backend.main:app --port 8000 &
API_PID=$!
trap "kill $API_PID 2>/dev/null" EXIT
sleep 3
echo "Empira is running: open http://localhost:8501"
python -m http.server 8501 --bind 127.0.0.1 --directory app/web
