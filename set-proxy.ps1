#requires -Version 5.1
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $Root ".env"
$listPath = Join-Path $Root "PROXY-LIST.txt"

Write-Host ""
Write-Host "ПОДКЛЮЧЕНИЕ ПРОКСИ" -ForegroundColor Cyan
Write-Host ""
Write-Host "Прокси боту не нужен: он и так ходит в Telegram напрямую."
Write-Host "Здесь он нужен, только если провайдер закроет прямой путь."
Write-Host "Прямой путь останется главным, прокси будет запасным."
Write-Host ""

if (-not (Test-Path -LiteralPath $envPath)) {
    Write-Host "Файл .env не найден. Сначала запустите START-BOT.cmd." -ForegroundColor Red
    exit 1
}

$candidates = @()
if (Test-Path -LiteralPath $listPath) {
    $candidates = @(Get-Content -LiteralPath $listPath |
        Where-Object { $_ -match '^socks5://' } |
        ForEach-Object { ($_ -split '\s+')[0] } |
        Select-Object -First 5)
}

if ($candidates.Count -gt 0) {
    Write-Host "Проверенные прокси (самые быстрые сверху):" -ForegroundColor Yellow
    for ($i = 0; $i -lt $candidates.Count; $i++) {
        Write-Host ("  " + ($i + 1) + ". " + $candidates[$i])
    }
    Write-Host ""
    $answer = (Read-Host "Номер из списка, или свой адрес вида socks5://1.2.3.4:1080 (Enter — первый)").Trim()
} else {
    $answer = (Read-Host "Адрес прокси, например socks5://1.2.3.4:1080").Trim()
}

if ([string]::IsNullOrWhiteSpace($answer)) {
    if ($candidates.Count -eq 0) {
        Write-Host "Адрес не указан." -ForegroundColor Red
        exit 1
    }
    $proxy = $candidates[0]
} elseif ($answer -match '^\d+$' -and [int]$answer -ge 1 -and [int]$answer -le $candidates.Count) {
    $proxy = $candidates[[int]$answer - 1]
} else {
    $proxy = $answer
}

if ($proxy -notmatch '^(socks5|socks4|http|https)://[^\s/]+:\d{1,5}$') {
    Write-Host "Непохоже на адрес прокси. Нужен вид socks5://1.2.3.4:1080" -ForegroundColor Red
    exit 1
}

function Set-EnvValue([string]$Path, [string]$Key, [string]$Value) {
    $lines = @()
    if (Test-Path -LiteralPath $Path) { $lines = @(Get-Content -LiteralPath $Path) }
    $updated = $false
    $result = foreach ($line in $lines) {
        if ($line -match ("^" + [regex]::Escape($Key) + "=")) {
            "$Key=$Value"
            $updated = $true
        } else { $line }
    }
    if (-not $updated) { $result = @($result) + "$Key=$Value" }
    [IO.File]::WriteAllLines($Path, [string[]]$result, (New-Object Text.UTF8Encoding($false)))
}

Set-EnvValue $envPath "TELEGRAM_PROXY" $proxy
Write-Host ""
Write-Host "В .env записано: TELEGRAM_PROXY=$proxy" -ForegroundColor Green
Write-Host ""
Write-Host "Теперь запустите NET-CHECK.cmd — он проверит прокси и скажет, работает ли он."
Write-Host "Затем перезапустите бота (START-BOT.cmd)."
Write-Host "Вернуть работу без прокси: NO-PROXY.cmd."
Write-Host ""
