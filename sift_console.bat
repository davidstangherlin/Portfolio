@echo off
rem Sift console: double-click after a reboot to get a PowerShell window ready
rem for Sift's scripts (README, "After a reboot").
rem It checks PostgreSQL is running, gets the latest code, installs any new
rem packages, brings the database up to date, then leaves you at a PowerShell
rem prompt with Sift's Python (.venv) switched on. Close the window when done.
title Sift console
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Sift's Python environment isn't set up in %CD%\.venv
    echo See README.md, Setup.
    pause
    exit /b 1
)

echo [1/4] PostgreSQL
powershell -NoProfile -Command "$s = Get-Service postgresql* -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $s) { exit 2 }; if ($s.Status -eq 'Running') { Write-Host ('      ' + $s.Name + ' is running'); exit 0 }; try { Start-Service $s.Name -ErrorAction Stop; Write-Host ('      started ' + $s.Name); exit 0 } catch { exit 1 }"
if errorlevel 2 (
    echo       No PostgreSQL service found. Is PostgreSQL installed on this PC?
) else if errorlevel 1 (
    echo       PostgreSQL is stopped and couldn't be started from here.
    echo       Right-click this file and choose "Run as administrator", or start it in Services.
)

echo [2/4] Latest code
where git >nul 2>&1
if errorlevel 1 (
    echo       git isn't installed; skipped
) else (
    git pull --ff-only || echo       Couldn't update ^(local changes, or offline^); carrying on with the code you have.
)

echo [3/4] Python packages
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || echo       Package install failed; see the message above.

echo [4/4] Database
".venv\Scripts\python.exe" -m src.apply_schema
if errorlevel 1 (
    echo       Couldn't reach the database. Check PostgreSQL is running and DATABASE_URL in .env.
    echo       Runbook: docs\kb\operations\rb-database-connection.md
)

rem PowerShell 7 if installed, else Windows PowerShell. The execution policy
rem is bypassed for this window only, so Activate.ps1 and Sift's .ps1 scripts
rem run without changing the PC's setting.
set "PS=powershell"
where pwsh >nul 2>&1 && set "PS=pwsh"
echo.
echo Ready. PowerShell, in %CD%, with Sift's Python switched on. Common commands:
echo   python gui.py                      start Sift (or double-click start_sift.bat)
echo   python screen_asx.py               the screener in this window
echo   python -m src.search.reindex       rebuild search
echo   python -m src.graph.export         write the graph files to data\graph
echo   python -m pytest -q                run the tests (needs requirements-dev.txt)
echo   .\scripts\daily_refresh.ps1        run the nightly job now
echo.
%PS% -NoLogo -NoExit -ExecutionPolicy Bypass -Command "& '.\.venv\Scripts\Activate.ps1'"
