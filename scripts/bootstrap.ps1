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
$Requirements = Join-Path $Root "requirements.lock"
$DepsStateFile = Join-Path $RuntimeRoot "deps.state.json"
$PinnedPython = (Get-Content -LiteralPath (Join-Path $Root "PYTHON_VERSION") -Raw).Trim()
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

function Write-Step([string]$Text) { Write-Host "[Kohakuyasha] $Text" -ForegroundColor Yellow }

function Test-Python([string]$Exe) {
    if (-not (Test-Path -LiteralPath $Exe)) { return $false }
    try {
        & $Exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Get-SystemPython {
    $candidates = @()
    try {
        if (Get-Command py.exe -ErrorAction SilentlyContinue) {
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

function Enable-EmbeddedSite([string]$PythonRoot) {
    $pth = Get-ChildItem -LiteralPath $PythonRoot -Filter "python*._pth" | Select-Object -First 1
    if ($pth) {
        $lines = Get-Content -LiteralPath $pth.FullName
        $lines = $lines | ForEach-Object { if ($_ -match '^\s*#\s*import site\s*$') { "import site" } else { $_ } }
        if (-not ($lines -contains "import site")) { $lines += "import site" }
        Set-Content -LiteralPath $pth.FullName -Value $lines -Encoding ASCII
    }
}

function Install-PortablePython {
    Write-Step "Устанавливаю закреплённый переносимый Python $PinnedPython..."
    if (Test-Path -LiteralPath $PortableRoot) { Remove-Item -LiteralPath $PortableRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $PortableRoot | Out-Null

    $arch = "amd64"
    if ($env:PROCESSOR_ARCHITECTURE -match "ARM64") { $arch = "arm64" }
    elseif ($env:PROCESSOR_ARCHITECTURE -match "86") { $arch = "win32" }
    $url = "https://www.python.org/ftp/python/$PinnedPython/python-$PinnedPython-embed-$arch.zip"
    $zip = Join-Path $RuntimeRoot "python-$PinnedPython-$arch.zip"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
    Expand-Archive -LiteralPath $zip -DestinationPath $PortableRoot -Force
    Remove-Item -LiteralPath $zip -Force
    Enable-EmbeddedSite $PortableRoot

    $python = Join-Path $PortableRoot "python.exe"
    $pipOk = $false
    try { & $python -m pip --version 2>$null; $pipOk = ($LASTEXITCODE -eq 0) } catch {}
    if (-not $pipOk) {
        Write-Step "Устанавливаю pip в переносимый runtime..."
        $getPip = Join-Path $RuntimeRoot "get-pip.py"
        Invoke-WebRequest -UseBasicParsing -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip
        & $python $getPip --disable-pip-version-check
        if ($LASTEXITCODE -ne 0) { throw "Не удалось установить pip." }
        Remove-Item -LiteralPath $getPip -Force
    }
    return $python
}

function Ensure-Environment {
    $portable = Join-Path $PortableRoot "python.exe"
    if (Test-Python $portable) {
        return @{ Python = $portable; PythonW = (Join-Path $PortableRoot "pythonw.exe"); Kind = "portable" }
    }

    $venvPython = Join-Path $VenvRoot "Scripts\python.exe"
    if ((Test-Path -LiteralPath $VenvRoot) -and -not (Test-Python $venvPython)) {
        Write-Step "Удаляю повреждённое виртуальное окружение..."
        Remove-Item -LiteralPath $VenvRoot -Recurse -Force
    }

    $systemPython = Get-SystemPython
    if ($systemPython) {
        Write-Step "Найден системный Python. Подготавливаю локальное venv..."
        if (-not (Test-Python $venvPython)) {
            & $systemPython -m venv $VenvRoot
            if ($LASTEXITCODE -ne 0) { throw "Не удалось создать виртуальное окружение." }
        }
        return @{ Python = $venvPython; PythonW = (Join-Path $VenvRoot "Scripts\pythonw.exe"); Kind = "venv" }
    }

    if (Test-Path -LiteralPath $VenvRoot) { Remove-Item -LiteralPath $VenvRoot -Recurse -Force }
    $python = Install-PortablePython
    return @{ Python = $python; PythonW = (Join-Path $PortableRoot "pythonw.exe"); Kind = "portable" }
}

function Get-EnvironmentFingerprint([string]$Python, [string]$Kind) {
    $pythonHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Python).Hash
    $requirementsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Requirements).Hash
    $version = (& $Python -c "import sys; print(sys.version.split()[0])").Trim()
    return @{ python_sha256 = $pythonHash; python_version = $version; requirements_sha256 = $requirementsHash; kind = $Kind }
}

function Test-RuntimeImports([string]$Python) {
    & $Python -c "import fastapi,uvicorn,pystray,PIL,psutil" 2>$null
    return ($LASTEXITCODE -eq 0)
}

try {
    Write-Step "Проверяю окружение..."
    $envInfo = Ensure-Environment
    $python = $envInfo.Python
    $pythonw = $envInfo.PythonW
    if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $python }

    $fingerprint = Get-EnvironmentFingerprint $python $envInfo.Kind
    $needInstall = $true
    if (Test-Path -LiteralPath $DepsStateFile) {
        try {
            $old = Get-Content -LiteralPath $DepsStateFile -Raw | ConvertFrom-Json
            $needInstall = -not (
                $old.python_sha256 -eq $fingerprint.python_sha256 -and
                $old.python_version -eq $fingerprint.python_version -and
                $old.requirements_sha256 -eq $fingerprint.requirements_sha256 -and
                $old.kind -eq $fingerprint.kind
            )
        } catch { $needInstall = $true }
    }
    if (-not $needInstall) { $needInstall = -not (Test-RuntimeImports $python) }

    if ($needInstall) {
        Write-Step "Устанавливаю закреплённые runtime-зависимости..."
        & $python -m pip install --disable-pip-version-check -r $Requirements
        if ($LASTEXITCODE -ne 0) { throw "Не удалось установить runtime-зависимости." }
        $fingerprint | ConvertTo-Json | Set-Content -LiteralPath $DepsStateFile -Encoding UTF8
        if (-not (Test-RuntimeImports $python)) { throw "Проверка runtime-зависимостей не прошла." }
    } else {
        Write-Step "Runtime готов."
    }

    Write-Step "Запускаю Kohakuyasha..."
    $launcherArgs = "`"$Root\launcher.pyw`""
    if ($SafeMode) { $launcherArgs += " --safe" }
    Start-Process -FilePath $pythonw -ArgumentList $launcherArgs -WorkingDirectory $Root
    Write-Step "Готово. Kohakuyasha работает в области уведомлений."
    Start-Sleep -Milliseconds 500
} catch {
    Write-Host ""
    Write-Host "Ошибка запуска Kohakuyasha:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Нажмите Enter, чтобы закрыть окно." -ForegroundColor Gray
    Read-Host | Out-Null
    exit 1
}
