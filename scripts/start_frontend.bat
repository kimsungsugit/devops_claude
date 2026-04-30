@echo off
title ARIA Frontend Dev Server
cd /d "%~dp0\..\frontend-v2"
echo ============================================
echo  ARIA Frontend Dev Server
echo ============================================
echo.
echo Dev server: http://localhost:5174
echo (API requests proxy to http://127.0.0.1:9000)
echo.
echo Press Ctrl+C to stop.
echo.

if not exist "node_modules" (
  echo node_modules not found. Running npm install...
  npm install
)

npm run dev
pause
