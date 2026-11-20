@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Обновление VIN Telegram Bot
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0update-bot.ps1" %*
if errorlevel 1 (
  echo.
  echo Обновление не удалось: смотрите сообщения выше.
  pause
  exit /b 1
)
pause
endlocal
