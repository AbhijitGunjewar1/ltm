@echo off
setlocal

echo ============================================================
echo  iTime Timesheet Filler
echo ============================================================
echo.

REM ── ITIME_SESSION ────────────────────────────────────────────
if "%ITIME_SESSION%"=="" (
    set /p ITIME_SESSION="Enter ITIME_SESSION (base64 auth): "
)
if "%ITIME_SESSION%"=="" (
    echo ERROR: ITIME_SESSION is required.
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
