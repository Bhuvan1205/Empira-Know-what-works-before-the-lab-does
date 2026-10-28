@echo off
REM Starts the Empira API (port 8000) and the web app (port 8501), then opens the browser.
REM Needs: pip install -r requirements.txt -r app\requirements.txt
cd /d "%~dp0\.."
start "Empira API" cmd /k python -m uvicorn app.backend.main:app --port 8000
timeout /t 3 /nobreak >nul
start "Empira app" cmd /k python -m http.server 8501 --bind 127.0.0.1 --directory app\web
timeout /t 2 /nobreak >nul
start http://localhost:8501
