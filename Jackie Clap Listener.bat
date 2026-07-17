@echo off
rem ============================================================
rem  Jackie clap listener - keep this window running (minimized
rem  is fine). Double-clap your hands and the Jackie dashboard
rem  opens by itself, ready for "Hey Jackie".
rem  Want it always on? Press Win+R, type  shell:startup  and
rem  drop a shortcut to this .bat in that folder.
rem ============================================================
setlocal
cd /d "%~dp0"

set "VENV=.venv"

if not exist "%VENV%\Scripts\python.exe" (
    echo First run detected - setting up Jackie. This takes a minute...
    where py >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python was not found. Install Python 3.10+ from https://python.org
        pause
        exit /b 1
    )
    py -3 -m venv "%VENV%"
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip
    "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt
)

"%VENV%\Scripts\python.exe" "%~dp0clap_launcher.py"
pause
endlocal
