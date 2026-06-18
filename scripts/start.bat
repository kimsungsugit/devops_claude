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

REM --- 기동 전 사전점검 (2026-06-19): venv + 핵심 인증 의존성 -------------------
REM canonical 인터프리터는 backend\.venv. 시스템 Python으로 기동되면 bcrypt 미설치로
REM auth_service import이 ModuleNotFoundError를 내며 앱 전체가 죽었던 사례 방지.
set "PYEXE=backend\.venv\Scripts\python.exe"
if not exist "%PYEXE%" (
  echo [ERROR] canonical venv not found: %PYEXE%
  echo         backend\.venv 가 없습니다. 생성/복구 후 재시도:
  echo           python -m venv backend\.venv
  echo           backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
  pause
  exit /b 1
)
"%PYEXE%" -c "import bcrypt, jwt" 1>nul 2>nul
if errorlevel 1 (
  echo [ERROR] 핵심 인증 의존성 누락 ^(bcrypt / PyJWT^).
  echo         backend.main:app import 시 ModuleNotFoundError 로 기동 실패합니다. 설치 후 재시도:
  echo           "%PYEXE%" -m pip install -r backend\requirements.txt
  pause
  exit /b 1
)
REM ---------------------------------------------------------------------------

"%PYEXE%" -m uvicorn backend.main:app --host 0.0.0.0 --port 9000
pause
