@echo off
echo ==============================================
echo [ITDA Backend] Starting FastAPI Server
echo Port: 8000
echo ==============================================
cd /d "%~dp0"
call uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
pause
