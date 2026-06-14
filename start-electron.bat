@echo off
setlocal

chcp 65001 >nul
title CLI Bridge Network Electron

set "ROOT=%~dp0"
cd /d "%ROOT%"

if not exist "package.json" (
  echo [ERROR] package.json not found under "%ROOT%".
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm was not found on PATH. Install Node.js, then run this script again.
  pause
  exit /b 1
)

if not exist "runtime" mkdir "runtime" >nul 2>nul

set "PYTHONUTF8=1"
set "CBN_DAEMON_HOST=127.0.0.1"
set "CBN_DAEMON_PORT=8787"
set "CBN_DAEMON_URL=http://127.0.0.1:8787"

echo Starting CLI Bridge Network Electron...
echo Working directory: %CD%
echo Daemon URL: %CBN_DAEMON_URL%
echo.

npm run app:dev

echo.
echo Electron exited with code %ERRORLEVEL%.
pause
exit /b %ERRORLEVEL%
