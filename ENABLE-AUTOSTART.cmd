@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  powershell.exe -NoLogo -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-setup.ps1" -InstallOnly
if errorlevel 1 goto :error
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable-autostart.ps1"
if errorlevel 1 goto :error
pause
exit /b 0
:error
pause
exit /b 1
