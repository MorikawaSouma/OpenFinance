@echo off
setlocal
cd /d %~dp0
powershell -ExecutionPolicy Bypass -File infra\scripts\start_dev.ps1 -Restart
endlocal
