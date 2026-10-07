@echo off
setlocal
chcp 65001 >nul
set "ROOT=%~dp0.."
if exist "%ROOT%\.runtime\venv\Scripts\python.exe" (
  set "PY=%ROOT%\.runtime\venv\Scripts\python.exe"
) else if exist "%ROOT%\.runtime\python\python.exe" (
  set "PY=%ROOT%\.runtime\python\python.exe"
) else (
  set "PY=python"
)
"%PY%" -m pytest -q "%ROOT%\tests"
pause
