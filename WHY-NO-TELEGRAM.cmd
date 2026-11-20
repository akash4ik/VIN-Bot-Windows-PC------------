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
echo Ищу, где именно обрывается путь к Telegram. Это займёт до минуты.
echo Ничего не меняю и не правлю: только смотрю.
echo.
".venv\Scripts\python.exe" -m app.whynot
echo.
pause
