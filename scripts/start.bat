@echo off
title ARIA Backend Server
cd /d "%~dp0\.."
echo ============================================
echo  ARIA Backend Server
echo  Automated Review and Intelligence Analyzer
echo ============================================
echo.
echo Backend: http://0.0.0.0:9000
echo Frontend: http://localhost:5174 (run scripts\start_frontend.bat separately)
echo.
echo Press Ctrl+C to stop.
echo.
backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 9000
pause
