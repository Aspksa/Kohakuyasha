@echo off
setlocal
chcp 65001 >nul
set "ROOT=%~dp0.."
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_tests.ps1" -Root "%ROOT%"
pause
