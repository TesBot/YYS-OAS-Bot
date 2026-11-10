@echo off
rem ============================================================
rem  OAS Engine setup
rem  Creates .venv with Python 3.10 and installs requirements.
rem  Prerequisite: Python 3.10 (python.exe / py -3.10) on PATH.
rem ============================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul

set PYEXE=
py -3.10 -c "print(1)" >nul 2>&1
if not errorlevel 1 set PYEXE=py -3.10
if not defined PYEXE (
  python -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 set PYEXE=python
)
if not defined PYEXE (
  echo [ERROR] Python 3.10 not found.
  echo Please install Python 3.10 from https://www.python.org/downloads/release/python-31011/
  echo and make sure it is on PATH, then run this script again.
  pause
  exit /b 1
)

echo [1/3] Creating virtual environment (.venv) ...
if exist ".venv\Scripts\python.exe" (
  echo .venv already exists, skipping creation.
) else (
  %PYEXE% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create .venv
    pause
    exit /b 1
  )
)

echo [2/3] Upgrading pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 echo [WARN] pip upgrade failed, continuing.

echo [3/3] Installing requirements (this may take several minutes) ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo [ERROR] Failed to install requirements.
  echo If the mirror is unreachable, try the default index:
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

echo.
echo Setup finished. You can now open OAS Studio and select this folder
echo   %cd%
echo as the engine directory.
pause
