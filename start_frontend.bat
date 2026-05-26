@echo off
echo ==============================================
echo [ITDA Frontend] Starting No-Cache Server
echo Port: 3000
echo ==============================================
cd /d "%~dp0"
python no_cache_server.py
pause
