#requires -Version 5.1
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $Root ".env"

Write-Host ""
Write-Host "ОТКЛЮЧЕНИЕ ПРОКСИ" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path -LiteralPath $envPath)) {
    Write-Host "Файл .env не найден." -ForegroundColor Red
    exit 1
}

$lines = @(Get-Content -LiteralPath $envPath)
$kept = @($lines | Where-Object { $_ -notmatch '^\s*(export\s+)?TELEGRAM_PROXY\s*=' })
[IO.File]::WriteAllLines($envPath, [string[]]$kept, (New-Object Text.UTF8Encoding($false)))

Write-Host "Строка TELEGRAM_PROXY убрана из .env." -ForegroundColor Green
Write-Host "Бот снова ходит в Telegram напрямую, без прокси."
Write-Host ""
Write-Host "Перезапустите бота (START-BOT.cmd), если он сейчас работает."
Write-Host "Проверить: NET-CHECK.cmd."
Write-Host ""
