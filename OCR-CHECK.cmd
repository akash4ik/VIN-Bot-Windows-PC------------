@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Виртуальное окружение не найдено. Сначала запустите START-BOT.cmd
  pause
  exit /b 1
)
set "PHOTO=%~1"
if "%PHOTO%"=="" (
  echo.
  echo Перетащите сюда файл фотографии, либо введите путь к нему.
  echo.
  set /p PHOTO=Путь: 
)
echo.
echo Читаю. Это займёт около минуты.
echo.
".venv\Scripts\python.exe" -m app.ocrcheck "%PHOTO%"
echo.
echo Выделите весь текст выше и пришлите его.
pause
