#!/usr/bin/env bash
# Starts the API (port 8000) and the app (port 8501). Ctrl+C stops both.
# Needs: pip install -r requirements.txt -r app/requirements.txt
set -e
cd "$(dirname "$0")/.."
python -m uvicorn app.backend.main:app --port 8000 &
API_PID=$!
trap "kill $API_PID 2>/dev/null" EXIT
sleep 4
cd app/frontend
echo "Open http://localhost:8501"
python -m streamlit run streamlit_app.py --server.port 8501
