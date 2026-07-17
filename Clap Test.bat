@echo off
rem  Clap calibration - run this, clap a few times, read the verdict.
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" clap_test.py
endlocal
