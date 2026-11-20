@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Второй читатель VIN Telegram Bot
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0second-reader.ps1" %*
if errorlevel 1 (
  echo.
  echo Не удалось. Смотрите сообщения выше.
  pause
  exit /b 1
)
echo.
pause
endlocal
