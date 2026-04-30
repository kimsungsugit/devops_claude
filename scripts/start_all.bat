@echo off
title ARIA Launcher
cd /d "%~dp0\.."
echo ============================================
echo  ARIA - Starting Backend + Frontend
echo ============================================
echo.
echo This will open 2 windows:
echo   1) Backend  — http://localhost:9000
echo   2) Frontend — http://localhost:5174
echo.
echo Close those windows to stop the servers.
echo.
pause

start "ARIA Backend" cmd /k "%~dp0start.bat"
timeout /t 3 /nobreak > nul
start "ARIA Frontend" cmd /k "%~dp0start_frontend.bat"

echo.
echo Servers starting in separate windows.
echo Open http://localhost:5174 in your browser.
echo.
pause
