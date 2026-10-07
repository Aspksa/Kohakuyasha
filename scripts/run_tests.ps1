param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $Root).Path.TrimEnd("\")
$DevVenv = Join-Path $Root ".runtime\dev-venv"
$Python = $null
foreach ($candidate in @((Join-Path $Root ".runtime\venv\Scripts\python.exe"),(Join-Path $Root ".runtime\python\python.exe"))) {
    if (Test-Path -LiteralPath $candidate) { $Python = $candidate; break }
}
if (-not $Python) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd.Source }
}
if (-not $Python) { throw "Сначала запустите Kohakuyasha.bat, чтобы подготовить Python." }
$DevPython = Join-Path $DevVenv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $DevPython)) { & $Python -m venv $DevVenv }
& $DevPython -m pip install --disable-pip-version-check -r (Join-Path $Root "requirements-dev.lock")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $DevPython -m pytest -q (Join-Path $Root "tests")
exit $LASTEXITCODE
