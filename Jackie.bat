@echo off
rem ============================================================
rem  Jackie 1.0 launcher - double-click this to open the app.
rem  On first run it sets up a private Python environment and
rem  installs everything automatically, then opens the window.
rem ============================================================
setlocal
cd /d "%~dp0"

set "VENV=.venv"

if not exist "%VENV%\Scripts\pythonw.exe" (
    echo.
    echo First run detected - setting up Jackie. This takes a minute...
    echo.
    where py >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python was not found. Install Python 3.10+ from https://python.org
        echo Make sure to tick "Add Python to PATH" during installation.
        pause
        exit /b 1
    )
    py -3 -m venv "%VENV%"
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip
    "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt
    echo.
    echo Setup complete. Launching Jackie...
)

start "" "%VENV%\Scripts\pythonw.exe" "%~dp0server.py"
endlocal
