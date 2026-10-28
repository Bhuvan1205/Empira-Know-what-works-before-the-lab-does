@echo off
REM Starts the API (port 8000) and the app (port 8501), then opens the browser.
REM Run from anywhere; needs: pip install -r requirements.txt -r app\requirements.txt
cd /d "%~dp0\.."
start "Empira API" cmd /k python -m uvicorn app.backend.main:app --port 8000
timeout /t 4 /nobreak >nul
cd app\frontend
start "Empira app" cmd /k python -m streamlit run streamlit_app.py --server.port 8501
timeout /t 5 /nobreak >nul
start http://localhost:8501
