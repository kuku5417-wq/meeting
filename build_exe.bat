@echo off
title meeting - build exe
REM meeting - build a standalone folder app (step 11, 2026-11-24).
REM Output: dist\meeting\meeting.exe  (copy the whole dist\meeting folder)
REM pyinstaller is NOT a project dependency - we pull it only for the build,
REM so uv.lock stays the same for the PCs that just run the app.
cd /d "%~dp0"
echo [1/2] build (pyinstaller)
uv run --with "pyinstaller>=6.10" pyinstaller meeting.spec --noconfirm --clean
if errorlevel 1 (
    echo [FAIL] build failed. On the corporate net run setup_env.bat first ^(proxy^).
    pause
    exit /b 1
)
echo.
echo [2/2] done: dist\meeting\meeting.exe
echo     The app still reads secret\.env from a parent folder and data from ^<base^>\meeting.
echo     Put .claude\shi.json next to the exe folder only if you need net=internal.
pause
exit /b
