@echo off
rem Starts Sift: double-click this file (README, Web GUI).
rem It uses Sift's own Python in .venv, so PowerShell's script setting doesn't matter.
rem Leave the window open while you use Sift; close it (or press Ctrl+C) to stop.
title Sift
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Sift's Python environment isn't set up in %CD%\.venv
    echo See README.md, Setup.
    pause
    exit /b 1
)
rem Open the browser a few seconds after the server starts.
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8000"
".venv\Scripts\python.exe" gui.py %*
echo.
echo Sift has stopped. If that wasn't you, the message above says why.
pause
