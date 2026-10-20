@echo off
setlocal
chcp 65001 >nul 2>&1
title API Scheduler

cd /d "%~dp0"

set "PY="
REM 1. project virtualenv
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
REM 2. user-level Python installs (e.g. Python313/Python314)
if not defined PY for /d %%P in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if not defined PY if exist "%%P\python.exe" set "PY=%%P\python.exe"
REM 3. pythoncore portable builds (e.g. pythoncore-3.14-64)
if not defined PY for /d %%P in ("%LOCALAPPDATA%\Python\pythoncore-*") do if not defined PY if exist "%%P\python.exe" set "PY=%%P\python.exe"
REM 4. C:\Python3*
if not defined PY for /d %%P in ("C:\Python3*") do if not defined PY if exist "%%P\python.exe" set "PY=%%P\python.exe"
REM 5. WorkBuddy managed python (deps already installed)
if not defined PY if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
REM 6. common non-C drive install (this machine: D:\Program Files\Python310)
if not defined PY if exist "D:\Program Files\Python310\python.exe" set "PY=D:\Program Files\Python310\python.exe"
REM 7. fallback to PATH
if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 set "PY=python"
)

if not defined PY goto :no_python

echo ============================================================
echo API Scheduler
echo Python: %PY%
echo Working directory: %CD%
echo Optional arguments: --dry-run or --force
echo Press Ctrl+C to stop the scheduler
echo ============================================================

"%PY%" "%~dp0run_scheduler.py" %*
set "SCRIPT_EXIT=%ERRORLEVEL%"

if "%SCRIPT_EXIT%"=="0" (
    echo [%date% %time%] Scheduler exited normally
) else (
    echo [%date% %time%] Scheduler exited with code: %SCRIPT_EXIT%
)

echo.
pause
exit /b %SCRIPT_EXIT%

:no_python
echo [ERROR] Python interpreter was not found. Install Python or add it to PATH.
pause
exit /b 1
