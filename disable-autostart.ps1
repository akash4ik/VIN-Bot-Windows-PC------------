#requires -Version 5.1
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$TaskName = "VIN Telegram Bot"
try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Автозапуск отключён, фоновый бот остановлен." -ForegroundColor Green
    } else {
        Write-Host "Задача автозапуска не найдена."
    }
} catch {
    Write-Host "ОШИБКА: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Запустите DISABLE-AUTOSTART.cmd от имени администратора." -ForegroundColor Yellow
    exit 1
}
