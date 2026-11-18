@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Virtual environment missing. See README.md for setup.
  pause
  exit /b 1
)
if not exist frontend\out\index.html (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo The interface isn't built and Node.js isn't installed.
    echo Install Node.js 20 or newer, then run start.bat again.
    pause
    exit /b 1
  )
  echo Building the interface, first run only...
  pushd frontend
  call npm ci --no-fund --no-audit
  call npm run build
  popd
)
.venv\Scripts\python.exe server.py
pause
