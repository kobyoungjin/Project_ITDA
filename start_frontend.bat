@echo off
echo ==============================================
echo [ITDA Frontend] Starting Static Sever
echo Port: 3000
echo ==============================================
cd /d "%~dp0frontend"
python -m http.server 3000
pause
