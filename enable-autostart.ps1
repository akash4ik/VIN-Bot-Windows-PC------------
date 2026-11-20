#requires -Version 5.1
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "VIN Telegram Bot"

try {
    $pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path $pythonw)) { throw "pythonw.exe не найден. Сначала один раз запустите START-BOT.cmd." }

    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m app.main" -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = "PT20S"
    $settings = New-ScheduledTaskSettingsSet `
        -MultipleInstances IgnoreNew `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -WakeToRun
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
        -Description "VIN Telegram Bot: скрытый запуск, один экземпляр и автоматический перезапуск"
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3

    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    $currentState = (Get-ScheduledTask -TaskName $TaskName).State.ToString()
    $stateText = if ($currentState -eq "Running") { "Выполняется" } elseif ($currentState -eq "Ready") { "Готова" } else { $currentState }
    Write-Host "Автозапуск включён." -ForegroundColor Green
    Write-Host "Задача: $TaskName"
    Write-Host "Состояние: $stateText"
    Write-Host "Последний результат: $($info.LastTaskResult)"
    Write-Host "Бот запускается скрыто через 20 секунд после запуска Windows."
    Write-Host "Бот подключается к Telegram напрямую: VPN и прокси не нужны."
} catch {
    Write-Host "ОШИБКА: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Запустите ENABLE-AUTOSTART.cmd от имени администратора." -ForegroundColor Yellow
    exit 1
}
