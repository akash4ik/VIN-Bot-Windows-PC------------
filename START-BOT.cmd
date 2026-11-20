@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title VIN Telegram Bot
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-setup.ps1"
if errorlevel 1 pause
endlocal
