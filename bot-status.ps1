#requires -Version 5.1
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "VIN Telegram Bot"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    $stateText = switch ($task.State.ToString()) {
        "Running" { "Выполняется" }
        "Ready" { "Готова" }
        "Disabled" { "Отключена" }
        default { $task.State.ToString() }
    }
    Write-Host "Задача: $TaskName" -ForegroundColor Cyan
    Write-Host "Состояние: $stateText"
    Write-Host "Последний запуск: $($info.LastRunTime)"
    Write-Host "Последний результат: $($info.LastTaskResult)"
    Write-Host "Следующий запуск: $($info.NextRunTime)"
} else {
    Write-Host "Автозапуск не включён." -ForegroundColor Yellow
}

$processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'app\.main'
}
if ($processes) {
    Write-Host "`nПроцесс бота: ЗАПУЩЕН" -ForegroundColor Green
    $processes | ForEach-Object { Write-Host "PID $($_.ProcessId) - $($_.Name)" }
} else {
    Write-Host "`nПроцесс бота не найден" -ForegroundColor Yellow
}

$envPath = Join-Path $Root ".env"
if (Test-Path $envPath) {
    $lines = Get-Content $envPath
    $channelLine = $lines | Where-Object { $_ -match '^ARCHIVE_CHANNEL_ID=' } | Select-Object -First 1
    $channelValue = if ($channelLine) { $channelLine.Substring("ARCHIVE_CHANNEL_ID=".Length).Trim() } else { "" }
    Write-Host "`nПодключение к Telegram:" -ForegroundColor Cyan
    Write-Host "  Прямое подключение: VPN и прокси не используются." -ForegroundColor Green
    $direct = Test-NetConnection -ComputerName api.telegram.org -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue
    if ($direct) {
        Write-Host "  api.telegram.org: доступен, бот ходит напрямую, без VPN и прокси." -ForegroundColor Green
    } else {
        Write-Host "  api.telegram.org: не отвечает прямо сейчас. Это не поломка бота: "
        Write-Host "  он ждёт и подключится сам, как только сеть вернётся." -ForegroundColor Yellow
    }
    Write-Host "`nАрхив в канале:" -ForegroundColor Cyan
    if ($channelValue) {
        Write-Host "  Канал: $channelValue" -ForegroundColor Green
    } else {
        Write-Host "  Архив отключён: ARCHIVE_CHANNEL_ID не задан." -ForegroundColor Yellow
    }
}

$log = Join-Path $Root "logs\bot.log"
if (Test-Path $log) {
    Write-Host "`nПоследние строки журнала:" -ForegroundColor Cyan
    Get-Content $log -Tail 25
} else {
    Write-Host "`nФайл журнала ещё не создан."
}
