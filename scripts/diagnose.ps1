param([Parameter(Mandatory=$true)][string]$Root)
$Root = (Resolve-Path $Root).Path.TrimEnd("\")
$state = Join-Path $Root "data\runtime.json"
if (-not (Test-Path -LiteralPath $state)) { Write-Host "Kohakuyasha не запущена." -ForegroundColor Yellow; exit 1 }
try { $runtime = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json } catch { Write-Host "runtime.json повреждён." -ForegroundColor Red; exit 1 }
$pidValue = [int]$runtime.pid
$port = [int]$runtime.port
$processAlive = $null -ne (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)
$tcpAlive = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue
Write-Host "PID: $pidValue  process=$processAlive"; Write-Host "Port: $port  tcp=$tcpAlive"
if ($processAlive -and $tcpAlive) { Start-Process "http://127.0.0.1:$port/#tests"; exit 0 }
exit 2
