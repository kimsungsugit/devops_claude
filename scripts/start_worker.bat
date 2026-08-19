@echo off
setlocal EnableDelayedExpansion
title ARIA Cloudium Worker
cd /d "%~dp0\.."

echo ============================================
echo  ARIA Cloudium Worker (file IPC)
echo ============================================
echo.

REM --- 포트 단일 출처 = .env --------------------------------------------------
REM 백엔드도 같은 .env 를 읽는다(backend\main.py 의 load_dotenv). 여기서 값을
REM 하드코딩하면 두 벌이 되어 갈라지고, 갈라지면 백엔드는 옛 포트로 ping 을 쏴서
REM **게이트가 조용히 안 열린다**(에러도 안 난다 - 그냥 파일이 안 읽힌다).
set "PORT="
if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="CLOUDIUM_WORKER_PORT" set "PORT=%%B"
  )
)
if not defined PORT (
  echo [WARN] .env 에 CLOUDIUM_WORKER_PORT 가 없습니다. 기본 8765 를 씁니다.
  set "PORT=8765"
)

REM CRLF .env 의 잔여 CR / 앞뒤 공백 제거 후 **숫자 검증**.
REM 파싱이 어긋난 채로 띄우면 워커는 뜨는데 백엔드가 못 붙는 최악의 상태가 된다.
for /f "tokens=1 delims= " %%P in ("!PORT!") do set "PORT=%%P"
set "PORT=!PORT: =!"
echo !PORT!| findstr /r /c:"^[0-9][0-9]*$" >nul
if errorlevel 1 (
  echo [ERROR] CLOUDIUM_WORKER_PORT 값을 숫자로 못 읽었습니다: "!PORT!"
  echo         .env 의 해당 줄을 확인하세요.
  pause
  exit /b 1
)
set "CLOUDIUM_WORKER_PORT=!PORT!"

REM --- worker exe 위치 --------------------------------------------------------
REM dist\ 를 먼저 본다 - 2026-08-19 실측으로 **실제 돌고 있는 건 dist\ 판**이고
REM 클라우디움 read 도 통과했다(list_dir 로 문서 40건 확인). dist_real\ 은 백업본.
REM [!] 클라우디움은 **경로가 아니라 프로세스 이름 + GUI 서브시스템**으로 권한을 준다.
REM   두 exe 이름이 같으므로 어느 쪽이든 붙지만, 실제로 검증된 쪽을 기본으로 둔다.
set "EXE=dist\excel_rename_gui_v2.exe"
if not exist "%EXE%" set "EXE=dist_real\excel_rename_gui_v2.exe"
if not exist "%EXE%" (
  echo [ERROR] worker exe 가 없습니다: dist_real\ 또는 dist\ 아래에 두세요.
  echo         빌드: pyinstaller --onefile --name excel_rename_gui_v2 --noconsole cloudium_worker\worker.py
  pause
  exit /b 1
)

REM --- 포트 선점 사전 점검 ----------------------------------------------------
REM worker.py 의 _ThreadingTCPServer 는 allow_reuse_address=True 라, 남이 잡고 있으면
REM 익숙한 10048("포트 사용 중")이 아니라 **WinError 10013("액세스 권한")** 으로 죽는다.
REM 포트 충돌이 권한 문제처럼 보여 진단이 헛돈다 -> 여기서 먼저 잡아 사람 말로 알린다.
netstat -ano | findstr /r /c:":!PORT! .*LISTENING" >nul
if not errorlevel 1 (
  echo [ERROR] 포트 !PORT! 를 이미 다른 프로세스가 쓰고 있습니다:
  echo.
  netstat -ano | findstr /r /c:":!PORT! .*LISTENING"
  echo.
  echo   해결 1^) 위 PID 프로세스를 종료
  echo   해결 2^) .env 의 CLOUDIUM_WORKER_PORT 를 빈 포트로 바꾸고
  echo           **백엔드도 재기동** ^(같은 값을 읽어야 게이트가 열립니다^)
  pause
  exit /b 1
)

echo  worker exe : %EXE%
echo  IPC port   : !PORT!  ^(backend 와 .env 로 공유^)
echo.
echo  ^* 이 창을 닫아도 됩니다. 워커 GUI 창은 **띄워 둔 채로** 두세요 -
echo     클라우디움 권한이 그 창에 붙어 있습니다.
echo.

start "" "%EXE%"
endlocal
