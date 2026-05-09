@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Package RouteForge App.ps1" -CreateZip
pause
