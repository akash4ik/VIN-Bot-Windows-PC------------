#requires -Version 5.1
# Переключение второго читателя (облако Google Gemini).
#
#   SECOND-READER.cmd first    — облако читает первым, бот — запасной путь
#   SECOND-READER.cmd auto     — облако только по трудным снимкам
#   SECOND-READER.cmd always   — облако по каждому снимку
#   SECOND-READER.cmd off      — облако не спрашивать
#   SECOND-READER.cmd          — просто показать, что стоит сейчас
#
param(
    [ValidateSet("first", "auto", "always", "off", "")]
    [string]$Mode = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "VIN Telegram Bot"

function Set-EnvValue($path, $name, $value) {
    $lines = @()
    if (Test-Path -LiteralPath $path) {
        $lines = @(Get-Content -LiteralPath $path)
    }
    $pattern = "^" + [regex]::Escape($name) + "="
    $newLine = "$name=$value"
    $out = New-Object System.Collections.Generic.List[string]
    $done = $false
    foreach ($line in $lines) {
        if ($line -match $pattern) {
            $out.Add($newLine)
            $done = $true
        } else {
            $out.Add($line)
        }
    }
    if (-not $done) { $out.Add($newLine) }
    [IO.File]::WriteAllLines($path, $out, (New-Object Text.UTF8Encoding($false)))
}

function Get-ReaderState {
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) { return $null }
    $snippet = @"
from app.config import Config
from app.vin_gemini import GeminiSettings
c = Config.from_env()
s = GeminiSettings(api_key=c.gemini_api_key, model=c.gemini_model, mode=c.gemini_mode, proxy=c.gemini_proxy)
print('mode=' + s.mode)
print('proxy=' + (s.proxy if s.proxy else 'net'))
print('model=' + s.model)
print('key=' + ('yes' if s.api_key else 'no'))
print('armed=' + ('yes' if s.cloud_reads_first else 'no'))
"@
    # Файл кладём РЯДОМ С БОТОМ, а не во временную папку: python ищет
    # модуль app в папке, откуда запущен, и из TEMP его не найдёт.
    $tmp = Join-Path $Root "_reader_probe.py"
    [IO.File]::WriteAllText($tmp, $snippet, (New-Object Text.UTF8Encoding($false)))
    try {
        $raw = & $venvPython $tmp 2>&1
    } finally {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Бот не смог прочитать свои настройки:" -ForegroundColor Red
        Write-Host ($raw -join "`n")
        return $null
    }
    $map = @{}
    foreach ($line in $raw) { if ($line -match "^([a-z]+)=(.*)$") { $map[$matches[1]] = $matches[2] } }
    return $map
}

function Write-State($map) {
    if (-not $map) { return }
    Write-Host ""
    Write-Host "  Режим : $($map['mode'])"
    Write-Host "  Модель: $($map['model'])"
    if ($map['proxy'] -eq 'net') {
        Write-Host "  Прокси: не задан, запрос идёт напрямую"
    } else {
        Write-Host "  Прокси: $($map['proxy'])" -ForegroundColor Green
    }
    if ($map['key'] -eq 'yes') {
        Write-Host "  Ключ  : указан" -ForegroundColor Green
    } else {
        Write-Host "  Ключ  : НЕ УКАЗАН" -ForegroundColor Yellow
    }
    if ($map['armed'] -eq 'yes') {
        Write-Host "  Облако читает первым: ДА" -ForegroundColor Green
    } else {
        Write-Host "  Облако читает первым: нет" -ForegroundColor Yellow
    }
}

Set-Location $Root
$envPath = Join-Path $Root ".env"

if (-not (Test-Path -LiteralPath $envPath)) {
    Write-Host "ОШИБКА: файл .env не найден рядом с ботом." -ForegroundColor Red
    Write-Host "Сначала один раз запустите START-BOT.cmd, он создаст .env." -ForegroundColor Yellow
    exit 1
}

if (-not $Mode) {
    Write-Host "Второй читатель: текущее состояние"
    $state = Get-ReaderState
    Write-State $state
    Write-Host ""
    Write-Host "Чтобы изменить: SECOND-READER.cmd first | auto | always | off"
    exit 0
}

# Ловушка: в старых сборках режим first не поддерживается, и бот при
# запуске с ним просто падает. Проверяем ДО того, как запишем.
$cfgPath = Join-Path $Root "app\config.py"
if (Test-Path -LiteralPath $cfgPath) {
    $cfgText = Get-Content -LiteralPath $cfgPath -Raw
    if ($cfgText -notmatch '"first"') {
        Write-Host "ОШИБКА: установленная версия бота не знает режим first." -ForegroundColor Red
        Write-Host ""
        Write-Host "Если записать first сейчас, бот перестанет запускаться."
        Write-Host "Сначала обновите бота: UPDATE-BOT.cmd (архив VIN-Bot-Windows-PC-v18.zip"
        Write-Host "положить рядом с ботом), затем снова запустите SECOND-READER.cmd first."
        exit 1
    }
}

Set-EnvValue $envPath "GEMINI_MODE" $Mode
Write-Host "В .env записано: GEMINI_MODE=$Mode" -ForegroundColor Green

$state = Get-ReaderState
if (-not $state) {
    Write-Host "Проверить не удалось — запустите бота и посмотрите экран «Второй читатель»."
    exit 1
}

Write-State $state

if ($Mode -ne "off" -and $state['key'] -ne 'yes') {
    Write-Host ""
    Write-Host "ВНИМАНИЕ: ключ Gemini не указан, поэтому режим $Mode ничего не меняет —"
    Write-Host "бот продолжит читать только сам." -ForegroundColor Yellow
    Write-Host "Бесплатный ключ: aistudio.google.com -> Get API key. Затем допишите в .env:"
    Write-Host "   GEMINI_API_KEY=AIza...ваш_ключ"
}

Write-Host ""
$restarted = $false
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    try {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        Start-Sleep -Seconds 2
        Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        $restarted = $true
        Write-Host "Бот перезапущен (задача «$TaskName»)." -ForegroundColor Green
    } catch {
        Write-Host "Задача «$TaskName» найдена, но перезапустить её не удалось." -ForegroundColor Yellow
        Write-Host "Запустите SECOND-READER.cmd от имени администратора" -ForegroundColor Yellow
        Write-Host "или перезагрузите компьютер — бот поднимется сам." -ForegroundColor Yellow
    }
}

if (-not $restarted) {
    Write-Host "Остановите бота (закройте его окно) и запустите START-BOT.cmd снова:" -ForegroundColor Yellow
    Write-Host "новый режим читается только при запуске." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Проверка в боте: Резервные копии -> Второй читатель -> Проверить ключ."
Write-Host "Там будет строка «Режим: first — облако читает первым, бот — запасной»."
