@echo off
setlocal
chcp 65001 >nul
set "KOH_ROOT=%~dp0"
title Kohakuyasha — запуск
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%KOH_ROOT%scripts\bootstrap.ps1" -Root "%KOH_ROOT%"
exit /b %ERRORLEVEL%
