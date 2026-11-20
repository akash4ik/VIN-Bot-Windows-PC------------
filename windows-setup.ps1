#requires -Version 5.1
param(
    [switch]$InstallOnly,
    [switch]$Reconfigure
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Write-Step([string]$Text) {
    Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

function Test-PythonPath([string]$Path) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $raw = & $Path -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $version = [version]($raw | Select-Object -Last 1)
        if ($version -ge [version]"3.11") { return (Resolve-Path $Path).Path }
    } catch { }
    return $null
}

function Find-Python {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "${env:ProgramFiles(x86)}\Python312\python.exe"
    )
    foreach ($candidate in $candidates) {
        $found = Test-PythonPath $candidate
        if ($found) { return $found }
    }

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $resolved = & $py.Source -3.12 -c "import sys; print(sys.executable)" 2>$null
            $found = Test-PythonPath ($resolved | Select-Object -Last 1)
            if ($found) { return $found }
        } catch { }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        $found = Test-PythonPath $python.Source
        if ($found) { return $found }
    }
    return $null
}

function Find-Tesseract {
    $candidates = @(
        "$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
        "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe",
        "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }
    $command = Get-Command tesseract.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return $null
}

function Convert-SecureStringToText([Security.SecureString]$Secure) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
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

function Read-TelegramIds([string]$Prompt, [bool]$AllowEmpty) {
    while ($true) {
        $raw = (Read-Host $Prompt).Trim()
        if (-not $raw) {
            if ($AllowEmpty) { return "" }
            Write-Warning "Нужно указать хотя бы один положительный Telegram ID."
            continue
        }
        if ($raw -notmatch '^[0-9]+(?:\s*,\s*[0-9]+)*$') {
            Write-Warning "Используйте только положительные числовые Telegram ID через запятую."
            continue
        }
        $ids = @()
        $valid = $true
        foreach ($item in $raw.Split(',')) {
            $parsedId = 0L
            if (-not [long]::TryParse($item.Trim(), [ref]$parsedId) -or $parsedId -le 0) {
                $valid = $false
                break
            }
            $ids += $parsedId
        }
        if (-not $valid) {
            Write-Warning "Один из Telegram ID недопустим."
            continue
        }
        return (($ids | Select-Object -Unique) -join ',')
    }
}

function Read-BotToken {
    while ($true) {
        $secureToken = Read-Host "Вставьте НОВЫЙ BOT_TOKEN от @BotFather" -AsSecureString
        $token = (Convert-SecureStringToText $secureToken).Trim()
        if ($token -match '^[1-9][0-9]{4,15}:[A-Za-z0-9_-]{30,}$') {
            return $token
        }
        Write-Warning "BOT_TOKEN имеет неверный формат. Скопируйте новый токен целиком из @BotFather."
    }
}

function Read-ArchiveChannel {
    while ($true) {
        $raw = (Read-Host "Telegram-канал для архива, например @allnewclear (Enter = архив отключён)").Trim()
        if (-not $raw) {
            Write-Warning "Без канала архив отключён: фотографии карточек останутся только в базе."
            return ""
        }
        $value = $raw -replace '^https?://(t\.me|telegram\.me)/', '@'
        if ($value -match '^@[A-Za-z0-9_]{4,32}$' -or $value -match '^-100\d{8,}$') {
            Write-Host "Канал архива: $value" -ForegroundColor Green
            Write-Host "Добавьте бота в этот канал администратором, иначе копии не отправятся." -ForegroundColor Yellow
            return $value
        }
        Write-Warning "Укажите канал как @имя (не короче 4 знаков) или как -1001234567890."
    }
}

function Read-GeminiKey {
    # Необязательно. Бот читает снимки сам; ключ лишь подключает второе
    # мнение — Google смотрит те фотографии, в которых бот не уверен.
    Write-Host ""
    Write-Host "ВТОРОЙ ЧИТАЕЦ (необязательно)" -ForegroundColor Cyan
    Write-Host "Бот сам читает VIN с фотографии, без интернета и без оплаты."
    Write-Host "Ключ Google Gemini нужен только как запасной читатель для"
    Write-Host "трудных снимков: блики, размытие, VIN на стекле."
    Write-Host "Без ключа бот работает как раньше."
    Write-Host ""
    $raw = (Read-Host "Ключ Gemini с aistudio.google.com (Enter = пропустить)").Trim()
    if (-not $raw) {
        Write-Host "Пропущено: бот читает только сам." -ForegroundColor DarkGreen
        return $null
    }
    if ($raw -match '\s' -or $raw.Length -lt 20) {
        Write-Warning "Ключ вставлен не целиком или с пробелом. Пропускаю: бот читает только сам."
        return $null
    }
    Write-Host "Ключ принят. Режим: auto — спрашивать облако только по трудным снимкам." -ForegroundColor Green
    return $raw
}

try {
    Write-Host "VIN Telegram Bot v18 — настройка для Windows" -ForegroundColor Green
    Write-Host "Существующие .env, база карточек и журналы сохраняются." -ForegroundColor DarkGreen

    Write-Step "1/5 Проверка Python 3.12"
    $python = Find-Python
    if (-not $python) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw "Python 3.12 не найден, а WinGet недоступен. Установите Python 3.12 с python.org, включите Add Python to PATH и снова запустите START-BOT.cmd."
        }
        Write-Host "Устанавливаю Python 3.12. Подтвердите запрос Windows, если он появится."
        & $winget.Source install --exact --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "WinGet не смог установить Python 3.12." }
        $python = Find-Python
        if (-not $python) { throw "Python установлен, но пока не найден. Перезагрузите Windows и снова запустите START-BOT.cmd." }
    }
    Write-Host "Python: $python"

    Write-Step "2/5 Проверка Tesseract OCR"
    $tesseract = Find-Tesseract
    if (-not $tesseract) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw "Tesseract OCR не найден. Установите версию UB Mannheim в C:\Program Files\Tesseract-OCR и повторите запуск."
        }
        Write-Host "Устанавливаю Tesseract OCR. Подтвердите установщик или запрос контроля учётных записей."
        & $winget.Source install --exact --id UB-Mannheim.TesseractOCR --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "WinGet не смог установить Tesseract OCR." }
        $tesseract = Find-Tesseract
        if (-not $tesseract) { throw "Tesseract установлен, но пока не найден. Перезагрузите Windows и снова запустите START-BOT.cmd." }
    }
    Write-Host "Tesseract: $tesseract"

    Write-Step "3/5 Установка библиотек Python"
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    $requirements = Join-Path $Root "requirements.txt"
    $stampPath = Join-Path $Root ".install-requirements.sha256"

    # A .venv carried over from another computer looks present and is not:
    # the paths baked into it point at the old machine. Ask it a question
    # before believing anything, because the stamp below only records that
    # pip ran once - somewhere, sometime, possibly on a different computer.
    $venvAlive = $false
    if (Test-Path -LiteralPath $venvPython) {
        & $venvPython -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { $venvAlive = $true }
    }
    if (-not $venvAlive) {
        if (Test-Path -LiteralPath $venvPython) {
            Write-Host "Виртуальное окружение с другого компьютера не работает — создаю заново." -ForegroundColor Yellow
        }
        Remove-Item -LiteralPath (Join-Path $Root ".venv") -Recurse -Force -ErrorAction SilentlyContinue
        & $python -m venv (Join-Path $Root ".venv")
        if ($LASTEXITCODE -ne 0) { throw "Не удалось создать виртуальное окружение .venv." }
        # Force the install below: whatever the stamp says, this venv is new.
        Remove-Item -LiteralPath $stampPath -Force -ErrorAction SilentlyContinue
    }
    $requirementsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirements).Hash
    $installedHash = if (Test-Path $stampPath) { (Get-Content $stampPath -Raw).Trim() } else { "" }
    if ($requirementsHash -ne $installedHash) {
        & $venvPython -m pip install --disable-pip-version-check --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "Не удалось обновить pip." }
        & $venvPython -m pip install --disable-pip-version-check -r $requirements
        if ($LASTEXITCODE -ne 0) { throw "Не удалось установить библиотеки Python. Проверьте интернет и антивирус." }
        [IO.File]::WriteAllText($stampPath, $requirementsHash, (New-Object Text.UTF8Encoding($false)))
    } else {
        Write-Host "Библиотеки уже установлены."
    }

    Write-Step "4/5 Токен и настройки"
    $envPath = Join-Path $Root ".env"
    if ($Reconfigure -and (Test-Path $envPath)) {
        Copy-Item $envPath "$envPath.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Remove-Item $envPath
    }
    if (-not (Test-Path -LiteralPath $envPath)) {
        $token = Read-BotToken
        $allowed = Read-TelegramIds "Telegram ID разрешённых пользователей через запятую (пусто = открытый доступ)" $true
        $admins = Read-TelegramIds "Telegram ID ГЛАВНЫХ администраторов через запятую (обязательно)" $false
        Write-Host "Бот подключается к Telegram напрямую: VPN и прокси не нужны." -ForegroundColor DarkGreen
        $channel = Read-ArchiveChannel
        $geminiKey = Read-GeminiKey
        $geminiMode = if ($geminiKey) { "auto" } else { "off" }
        if (-not $geminiKey) { $geminiKey = "" }
        $tesseractValue = $tesseract.Replace("\", "/")
        $content = @(
            "BOT_TOKEN=$token",
            "ALLOWED_USER_IDS=$allowed",
            "ADMIN_USER_IDS=$admins",
            "TIMEZONE=Europe/Berlin",
            "DATABASE_URL=sqlite+aiosqlite:///data/bot.db",
            "LOG_LEVEL=INFO",
            "TELEGRAM_PROXY=",
            "TELEGRAM_PREFER=direct",
            "FORCE_IPV4=true",
            "TESSERACT_CMD=$tesseractValue",
            "BACKUP_DIR=data/backups",
            "ARCHIVE_CHANNEL_ID=$channel",
            "ARCHIVE_IMMEDIATE=true",
            "ARCHIVE_DIGEST_TIME=23:30",
            "ARCHIVE_INCLUDE_INVOICE=true",
            "ARCHIVE_LANGUAGE=ru",
            "GEMINI_API_KEY=$geminiKey",
            "GEMINI_MODE=$geminiMode"
        )
        [IO.File]::WriteAllLines($envPath, $content, (New-Object Text.UTF8Encoding($false)))
        Write-Host "Настройки сохранены в локальный файл .env." -ForegroundColor Green
    } else {
        Set-EnvValue $envPath "TESSERACT_CMD" ($tesseract.Replace("\", "/"))
        Write-Host "Существующий .env сохранён без удаления токена и ID." -ForegroundColor Green
        $channelLine = (Get-Content $envPath | Where-Object { $_ -match '^ARCHIVE_CHANNEL_ID=' } | Select-Object -First 1)
        if (-not $channelLine -or $channelLine -eq "ARCHIVE_CHANNEL_ID=") {
            $channel = Read-ArchiveChannel
            if ($channel) { Set-EnvValue $envPath "ARCHIVE_CHANNEL_ID" $channel }
        }
        $geminiLine = (Get-Content $envPath | Where-Object { $_ -match '^GEMINI_API_KEY=' } | Select-Object -First 1)
        if ($geminiLine -and ($geminiLine -ne "GEMINI_API_KEY=")) {
            Write-Host "Второй читатель (Gemini) уже настроен." -ForegroundColor DarkGreen
        } else {
            $geminiKey = Read-GeminiKey
            if ($geminiKey) {
                Set-EnvValue $envPath "GEMINI_API_KEY" $geminiKey
                Set-EnvValue $envPath "GEMINI_MODE" "auto"
            } else {
                Set-EnvValue $envPath "GEMINI_MODE" "off"
            }
        }
    }
    # A .env carried over from another computer can name a setting this build
    # does not know - GEMINI_MODE=first is exactly that, and python's own
    # traceback names a file nobody opened. So the mode is checked here
    # first, in words, before python is asked anything.
    $modeLine = (Get-Content -LiteralPath $envPath | Where-Object { $_ -match '^GEMINI_MODE=' } | Select-Object -First 1)
    $modeValue = if ($modeLine) { $modeLine.Substring("GEMINI_MODE=".Length).Trim() } else { "" }
    if ($modeValue) {
        $cfgFile = Join-Path $Root "app\config.py"
        $knownModes = ""
        if (Test-Path -LiteralPath $cfgFile) {
            $cfgRaw = Get-Content -LiteralPath $cfgFile -Raw
            if ($cfgRaw -match 'VALID_GEMINI_MODES\s*=\s*frozenset\(\{([^}]*)\}\)') {
                $knownModes = $matches[1]
            }
        }
        if ($knownModes) {
            $modePattern = '"' + $modeValue + '"'
            if ($knownModes -notmatch [regex]::Escape($modePattern)) {
                throw ("В .env стоит GEMINI_MODE=$modeValue, но установленная версия бота такого режима не знает. Этот сборщик понимает:$knownModes. Либо обновите бота (UPDATE-BOT.cmd, рядом положить VIN-Bot-Windows-PC-v18.zip), либо поставьте в .env GEMINI_MODE=off.")
            }
        }
    }

    $configCheck = & $venvPython -c "from app.config import Config; Config.from_env()" 2>&1
    if ($LASTEXITCODE -ne 0) {
        # The whole error goes to a file and its tail goes on the screen: a
        # console window this size swallows a traceback whole, and a message
        # cut off at its first line is worse than no message at all.
        $logDir = Join-Path $Root "logs"
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        $errLog = Join-Path $logDir "setup-error.log"
        ($configCheck -join "`n") | Out-File -LiteralPath $errLog -Encoding utf8
        $tailLines = @($configCheck)
        if ($tailLines.Count -gt 12) {
            $tailLines = $tailLines[($tailLines.Count - 12)..($tailLines.Count - 1)]
        }
        throw ("Проверка .env не пройдена. Полный текст ошибки записан в $errLog`n" + ($tailLines -join "`n"))
    }
    Write-Host "Токен, Telegram ID и остальные настройки .env проверены." -ForegroundColor Green
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "data"), (Join-Path $Root "logs") | Out-Null

    Write-Step "5/5 Готово"
    Write-Host "Бот подключается к Telegram напрямую: VPN, прокси и другие программы не нужны." -ForegroundColor Green
    $channelLine = (Get-Content $envPath | Where-Object { $_ -match '^ARCHIVE_CHANNEL_ID=' } | Select-Object -First 1)
    $channelValue = if ($channelLine) { $channelLine.Substring("ARCHIVE_CHANNEL_ID=".Length).Trim() } else { "" }
    if ($channelValue) {
        Write-Host "Архив включён: канал $channelValue." -ForegroundColor Green
        Write-Host "Добавьте бота в канал администратором, иначе копии карточек не отправятся." -ForegroundColor Yellow
    } else {
        Write-Warning "Архив отключён: канал не указан. Проверить можно в боте: Резервные копии → Канал-архив."
    }

    if ($InstallOnly) {
        Write-Host "Установка завершена." -ForegroundColor Green
        exit 0
    }

    Write-Host "Запускаю бота. Не закрывайте это окно. Для остановки нажмите Ctrl+C." -ForegroundColor Green
    & $venvPython -m app.main
    exit $LASTEXITCODE
} catch {
    Write-Host "`nОШИБКА: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Можно прислать снимок этой ошибки, но никогда не показывайте .env или BOT_TOKEN." -ForegroundColor Yellow
    Read-Host "Нажмите Enter для закрытия"
    exit 1
}
