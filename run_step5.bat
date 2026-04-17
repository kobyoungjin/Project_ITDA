@echo off
echo ==============================================
echo [ITDA Project] Starting Step 5: Face Sync
echo Port: 3000
echo Path: step5_face_sync/frontend
echo ==============================================
cd /d "%~dp0step5_face_sync\frontend"
python -m http.server 3000
pause
