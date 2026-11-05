@echo off
rem Windows: double-click this file in File Explorer to start the travel photo tool.
rem The first run prepares a private environment in .venv\; later runs start directly.
rem See docs/decisions/0007-one-click-launcher.md.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python3"
)

if not defined PY (
  echo 找不到 Python 3.10 以上版本，無法啟動旅行照片整理。
  echo 請到 https://www.python.org/downloads/ 下載安裝 Python 3.10 以上版本。
  echo 安裝時請勾選「Add python.exe to PATH」，裝好後再點兩下這個啟動檔。
  echo.
  pause
  exit /b 1
)

%PY% launcher\bootstrap.py %*
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)
endlocal
