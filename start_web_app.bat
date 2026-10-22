@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_web_app.ps1"
if errorlevel 1 pause
