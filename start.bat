@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Virtual environment missing. See README.md for setup.
  pause
  exit /b 1
)
.venv\Scripts\python.exe server.py
pause
