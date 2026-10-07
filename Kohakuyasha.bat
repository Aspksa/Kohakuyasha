@echo off
setlocal
set "KOH_ROOT=%~dp0."
title Kohakuyasha
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%KOH_ROOT%\scripts\bootstrap.ps1" -Root "%KOH_ROOT%"
set "KOH_RC=%ERRORLEVEL%"
if not "%KOH_RC%"=="0" pause
exit /b %KOH_RC%
