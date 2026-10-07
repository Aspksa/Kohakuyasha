@echo off
setlocal
chcp 65001 >nul
set "ROOT=%~dp0.."
start "" "http://127.0.0.1:8710/#tests"
