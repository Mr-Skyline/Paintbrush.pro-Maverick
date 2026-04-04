@echo off
setlocal
cd /d "%~dp0"

call npm run desktop:battleship

if errorlevel 1 (
  echo.
  echo Battleship desktop launch failed.
  echo Please verify Node/npm dependencies are installed.
  pause
)

endlocal
