@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Виртуальное окружение не найдено. Сначала запустите START-BOT.cmd
  pause
  exit /b 1
)
echo.
echo Проверяю, как компьютер видит Telegram. Это займёт до минуты.
echo.
".venv\Scripts\python.exe" -m app.netcheck
echo.
pause
