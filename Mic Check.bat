@echo off
rem  Full microphone diagnosis - tells you exactly why audio input is dead.
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" mic_check.py
pause
endlocal
