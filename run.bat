@echo off
title meeting
REM meeting - APP LAUNCHER for the HOST/operating PC only (starts the server here).
REM Other PCs should NOT run this - they just open http://<host-ip>:8600
REM Starts server + auto-opens the browser. venv must exist (run setup_env.bat first).
set "PYEXE=%LOCALAPPDATA%\venvs\meeting\Scripts\python.exe"
set "PORT=8600"
if not exist "%PYEXE%" (
    echo [ERROR] local venv not found: %PYEXE%
    echo Run setup_env.bat first ^(creates venv + installs deps^).
    pause
    exit /b 1
)
cd /d "%~dp0"
echo Starting meeting ...   (stop: Ctrl+C in this window)
call :show_urls
REM open the browser after a short delay (server needs a few seconds to come up)
start "" /min cmd /c "timeout /t 3 >nul & start "" http://localhost:%PORT%"
REM 0.0.0.0 so the 7 departments can reach it from their own PCs
"%PYEXE%" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT%
exit /b

REM ---- print Local / Network URLs (uvicorn only shows 0.0.0.0 = "all addresses") ----
REM lists every IPv4 of this PC except loopback 127.x and APIPA 169.254.x
:show_urls
echo     Local:   http://localhost:%PORT%
set "LAN_FOUND="
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4"') do call :show_ip %%a
if not defined LAN_FOUND echo     Network: run ipconfig, use IPv4 -^> http://[IP]:%PORT%
exit /b
:show_ip
set "IP=%~1"
if "%IP%"=="" exit /b
if "%IP:~0,4%"=="127." exit /b
if "%IP:~0,8%"=="169.254." exit /b
echo     Network: http://%IP%:%PORT%   ^(other PC^)
set "LAN_FOUND=1"
exit /b
