@echo off
setlocal
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed. Check Python and pip.
  pause
  exit /b 1
)
py yj64_remote_participant.py
pause
