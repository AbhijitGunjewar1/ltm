@echo off
setlocal

echo ============================================================
echo  iTime Timesheet Filler
echo ============================================================
echo.

REM ── ITIME_SESSION ────────────────────────────────────────────
REM Read from timesheet\session.txt if env var not already set
if "%ITIME_SESSION%"=="" (
    if exist "timesheet\session.txt" (
        set /p ITIME_SESSION=<timesheet\session.txt
    )
)
if "%ITIME_SESSION%"=="" (
    echo ERROR: ITIME_SESSION not found.
    echo.
    echo Create  timesheet\session.txt  and paste your base64 session value into it.
    echo Run  python timesheet\save_session.py  to generate it.
    pause & exit /b 1
)

REM ── TARGET_DATE (optional) ────────────────────────────────────
if "%TARGET_DATE%"=="" (
    set /p TARGET_DATE="Enter TARGET_DATE (YYYY-MM-DD) or leave blank for yesterday: "
)

REM ── HEADLESS ─────────────────────────────────────────────────
if "%HEADLESS%"=="" set HEADLESS=true

echo.
echo Installing dependencies...
pip install -r timesheet\requirements.txt --quiet
if errorlevel 1 ( echo ERROR: pip install failed. & pause & exit /b 1 )

echo Installing Playwright browser...
playwright install chromium
if errorlevel 1 ( echo ERROR: Playwright install failed. & pause & exit /b 1 )

echo.
if "%TARGET_DATE%"=="" (
    echo Target date : yesterday (default)
) else (
    echo Target date : %TARGET_DATE%
)
echo Headless     : %HEADLESS%
echo.

python timesheet\fill_timesheet.py
if errorlevel 1 (
    echo.
    echo ERROR: Script failed. Check output above.
    pause & exit /b 1
)

echo.
echo Done!
pause
