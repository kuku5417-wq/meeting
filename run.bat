@echo off
title meeting
REM meeting - APP LAUNCHER. Starts the server on THIS PC only (127.0.0.1).
REM Each department PC runs its own copy - no one connects to this one (shi rule, site policy).
REM venv must exist (run setup_env.bat first).
set "PYEXE=%LOCALAPPDATA%\venvs\meeting\Scripts\python.exe"
if not exist "%PYEXE%" (
    echo [ERROR] local venv not found: %PYEXE%
    echo Run setup_env.bat first ^(creates venv + installs deps^).
    pause
    exit /b 1
)
cd /d "%~dp0"

REM --- pick a free port on 127.0.0.1 (8600..8610). Another copy may already use 8600.
set "PORT="
for /f "delims=" %%P in ('"%PYEXE%" "%~dp0_freeport.py" 2^>nul') do set "PORT=%%P"
if not defined PORT (
    echo [ERROR] no free port in 8600-8610. Close other copies and try again.
    pause
    exit /b 1
)

echo Starting meeting ...   (stop: Ctrl+C in this window)
echo     Open:   http://127.0.0.1:%PORT%
echo     This server is local only - other PCs cannot reach it.
start "" /min cmd /c "timeout /t 3 >nul & start "" http://127.0.0.1:%PORT%"
"%PYEXE%" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
exit /b
