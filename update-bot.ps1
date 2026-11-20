#requires -Version 5.1
param(
    [string]$Archive
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "== $Text ==" -ForegroundColor Cyan
}

function Find-Archive([string]$Given) {
    if ($Given) {
        if (-not (Test-Path -LiteralPath $Given)) { throw "Архив не найден: $Given" }
        return (Resolve-Path $Given).Path
    }
    $places = @($Root, (Join-Path $env:USERPROFILE "Downloads"))
    $found = @()
    foreach ($place in $places) {
        if (-not (Test-Path -LiteralPath $place)) { continue }
        $found += @(Get-ChildItem -LiteralPath $place -Filter "VIN-Bot-Windows-PC-*.zip" -File -ErrorAction SilentlyContinue)
    }
    if ($found.Count -eq 0) {
        throw "ZIP-архив не найден. Положите его рядом с ботом или укажите путь: UPDATE-BOT.cmd C:\Users\Вы\Downloads\VIN-Bot-Windows-PC-v19.zip"
    }
    return ($found | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}

Write-Step "1/5 Какой архив ставим"
$zip = Find-Archive $Archive
Write-Host "Архив: $zip"

Write-Step "2/5 Останавливаем бота"
$taskName = "VIN Telegram Bot"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null
    Start-Sleep -Seconds 2
    Write-Host "Задача планировщика остановлена."
} else {
    Write-Host "Задачи планировщика нет: бот запускается через START-BOT.cmd."
}

$staging = Join-Path $env:TEMP ("vin-bot-update-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
$copied = 0
try {
    Write-Step "3/5 Распаковываем новую версию"
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $staging)
    if (-not (Test-Path -LiteralPath (Join-Path $staging "app\main.py"))) {
        throw "В архиве нет файла app\main.py — похоже, это не комплект бота."
    }

    # .env, база данных, снимки, журналы и виртуальное окружение не трогаются:
    # это ваши данные, а не часть программы. Сами скрипты обновления тоже
    # пропускаются, чтобы не перезаписать выполняемый файл на ходу.
    $protected = @(".env", "data", "backups", "logs", ".venv", "update-bot.ps1", "UPDATE-BOT.cmd")
    foreach ($item in (Get-ChildItem -LiteralPath $staging -Force)) {
        if ($protected -contains $item.Name) { continue }
        $target = Join-Path $Root $item.Name
        if ($item.PSIsContainer) {
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
            Copy-Item -LiteralPath $item.FullName -Destination $target -Recurse -Force
        } else {
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
        $copied++
        Write-Host "  обновлено: $($item.Name)"
    }

    Write-Step "4/5 Библиотеки Python"
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "Виртуального окружения нет: запустите START-BOT.cmd, он создаст его." -ForegroundColor Yellow
    } else {
        $requirements = Join-Path $Root "requirements.txt"
        $stampPath = Join-Path $Root ".install-requirements.sha256"
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirements).Hash
        $installed = ""
        if (Test-Path $stampPath) { $installed = (Get-Content $stampPath -Raw).Trim() }
        if ($hash -ne $installed) {
            & $venvPython -m pip install --disable-pip-version-check -r $requirements
            if ($LASTEXITCODE -ne 0) { throw "Не удалось установить библиотеки Python." }
            [IO.File]::WriteAllText($stampPath, $hash, (New-Object Text.UTF8Encoding($false)))
            Write-Host "Библиотеки обновлены."
        } else {
            Write-Host "Библиотеки уже актуальны."
        }
        & $venvPython -c "import app.main"
        if ($LASTEXITCODE -ne 0) { throw "Новая версия не запускается: смотрите ошибку выше." }
        Write-Host "Новая версия загружается без ошибок."
    }

    Write-Step "5/5 Запуск"
    if ($task) {
        Start-ScheduledTask -TaskName $taskName
        Write-Host "Бот запущен." -ForegroundColor Green
    } else {
        Write-Host "Запустите бота двойным щелчком по START-BOT.cmd." -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "Обновлено файлов и папок: $copied" -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}
