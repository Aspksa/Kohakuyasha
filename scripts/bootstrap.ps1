param(
    [Parameter(Mandatory=$true)]
    [string]$Root,
    [switch]$SafeMode
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $Root).Path.TrimEnd("\")
$RuntimeRoot = Join-Path $Root ".runtime"
$PortableRoot = Join-Path $RuntimeRoot "python"
$VenvRoot = Join-Path $RuntimeRoot "venv"
$Requirements = Join-Path $Root "requirements.txt"
$DepsHashFile = Join-Path $RuntimeRoot "deps.sha256"

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

function Write-Step([string]$Text) {
    Write-Host "[Kohakuyasha] $Text" -ForegroundColor Yellow
}

function Test-Python([string]$Exe) {
    if (-not (Test-Path $Exe)) { return $false }
    try {
        & $Exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-SystemPython {
    $candidates = @()
    try {
        $py = (Get-Command py.exe -ErrorAction SilentlyContinue)
        if ($py) {
            $probe = & py.exe -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $probe) { $candidates += $probe.Trim() }
        }
    } catch {}
    foreach ($name in @("python.exe", "python3.exe")) {
        try {
            $cmd = Get-Command $name -ErrorAction SilentlyContinue
            if ($cmd) { $candidates += $cmd.Source }
        } catch {}
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Python $candidate) { return $candidate }
    }
    return $null
}

function Install-PortablePython {
    Write-Step "Python 3.11+ не найден. Загружаю переносимый Python..."
    New-Item -ItemType Directory -Force -Path $PortableRoot | Out-Null

    $index = Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/"
    $versions = [regex]::Matches($index.Content, 'href="(3\.\d+\.\d+)/"') |
        ForEach-Object { $_.Groups[1].Value } |
        Sort-Object { [version]$_ } -Descending -Unique

    $arch = "amd64"
    if ($env:PROCESSOR_ARCHITECTURE -match "ARM64") { $arch = "arm64" }

    $selected = $null
    foreach ($ver in $versions) {
        if ([version]$ver -lt [version]"3.11.0") { continue }
        $url = "https://www.python.org/ftp/python/$ver/python-$ver-embed-$arch.zip"
        try {
            $head = Invoke-WebRequest -UseBasicParsing -Method Head -Uri $url -TimeoutSec 10
            if ($head.StatusCode -ge 200 -and $head.StatusCode -lt 400) {
                $selected = @{ Version = $ver; Url = $url }
                break
            }
        } catch {}
    }

    if (-not $selected) {
        throw "Не удалось найти переносимую сборку Python 3.11+ на python.org."
    }

    $zip = Join-Path $RuntimeRoot "python.zip"
    Write-Step "Загрузка Python $($selected.Version) ($arch)..."
    Invoke-WebRequest -UseBasicParsing -Uri $selected.Url -OutFile $zip
    if (Test-Path $PortableRoot) { Remove-Item $PortableRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $PortableRoot | Out-Null
    Expand-Archive -Path $zip -DestinationPath $PortableRoot -Force
    Remove-Item $zip -Force

    $pth = Get-ChildItem $PortableRoot -Filter "python*._pth" | Select-Object -First 1
    if ($pth) {
        $content = Get-Content $pth.FullName
        $content = $content | ForEach-Object {
            if ($_ -match '^\s*#\s*import site\s*$') { "import site" } else { $_ }
        }
        if (-not ($content -contains "import site")) { $content += "import site" }
        Set-Content -Path $pth.FullName -Value $content -Encoding ASCII
    }

    $python = Join-Path $PortableRoot "python.exe"
    $pipProbe = & $python -m pip --version 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Step "Устанавливаю pip..."
        $getPip = Join-Path $RuntimeRoot "get-pip.py"
        Invoke-WebRequest -UseBasicParsing -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip
        & $python $getPip --disable-pip-version-check
        if ($LASTEXITCODE -ne 0) { throw "Не удалось установить pip." }
        Remove-Item $getPip -Force
    }
    return $python
}

function Ensure-Environment {
    $portable = Join-Path $PortableRoot "python.exe"
    if (Test-Python $portable) {
        return @{ Python = $portable; PythonW = (Join-Path $PortableRoot "pythonw.exe"); Kind = "portable" }
    }

    $systemPython = Get-SystemPython
    if ($systemPython) {
        Write-Step "Найден системный Python. Подготавливаю изолированное окружение..."
        $venvPython = Join-Path $VenvRoot "Scripts\python.exe"
        if (-not (Test-Python $venvPython)) {
            if (Test-Path $VenvRoot) { Remove-Item $VenvRoot -Recurse -Force }
            & $systemPython -m venv $VenvRoot
            if ($LASTEXITCODE -ne 0) { throw "Не удалось создать виртуальное окружение." }
        }
        return @{ Python = $venvPython; PythonW = (Join-Path $VenvRoot "Scripts\pythonw.exe"); Kind = "venv" }
    }

    $python = Install-PortablePython
    return @{ Python = $python; PythonW = (Join-Path $PortableRoot "pythonw.exe"); Kind = "portable" }
}

try {
    Write-Step "Проверяю окружение..."
    $envInfo = Ensure-Environment
    $python = $envInfo.Python
    $pythonw = $envInfo.PythonW
    if (-not (Test-Path $pythonw)) { $pythonw = $python }

    $reqHash = (Get-FileHash -Algorithm SHA256 $Requirements).Hash
    $oldHash = ""
    if (Test-Path $DepsHashFile) { $oldHash = (Get-Content $DepsHashFile -Raw).Trim() }

    if ($reqHash -ne $oldHash) {
        Write-Step "Устанавливаю/обновляю зависимости..."
        & $python -m pip install --disable-pip-version-check --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "Не удалось обновить pip." }
        & $python -m pip install --disable-pip-version-check -r $Requirements
        if ($LASTEXITCODE -ne 0) { throw "Не удалось установить зависимости." }
        Set-Content -Path $DepsHashFile -Value $reqHash -Encoding ASCII
    } else {
        Write-Step "Зависимости готовы."
    }

    Write-Step "Проверяю установку..."
    & $python -m pytest -q "$Root\tests" --disable-warnings
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Некоторые тесты не прошли. Запуск продолжен; подробности доступны в разделе диагностики."
    }

    Write-Step "Запускаю Kohakuyasha..."
    $launcherArgs = "`"$Root\launcher.pyw`""
    if ($SafeMode) { $launcherArgs += " --safe" }
    Start-Process -FilePath $pythonw -ArgumentList $launcherArgs -WorkingDirectory $Root
    Write-Step "Готово. Kohakuyasha работает в области уведомлений."
    Start-Sleep -Milliseconds 800
} catch {
    Write-Host ""
    Write-Host "Ошибка запуска Kohakuyasha:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Нажмите Enter, чтобы закрыть окно." -ForegroundColor Gray
    Read-Host | Out-Null
    exit 1
}
