param(
    [int]$Port = 5000
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment Python was not found: $python"
}

# The console is deliberately bound to localhost.  Only a listener on the
# requested console port is stopped, so a stale web_app.py cannot keep serving
# an older UI after this launcher starts the current workspace version.
$listenerLines = @(netstat.exe -ano -p tcp | Select-String -Pattern ("127\.0\.0\.1:{0}\s+.*LISTENING" -f $Port))
foreach ($listenerLine in $listenerLines) {
    $parts = ($listenerLine.ToString().Trim() -replace '\s+', ' ').Split(' ')
    $listenerPid = [int]$parts[-1]
    $process = Get-Process -Id $listenerPid -ErrorAction SilentlyContinue
    if ($process) {
        Write-Host "Stopping existing listener on port ${Port}: PID $($process.Id) ($($process.ProcessName))"
        Stop-Process -Id $process.Id -Force
    }
}

$env:WEB_APP_PORT = [string]$Port
$env:WEB_APP_OPEN_BROWSER = 'false'
$process = Start-Process -FilePath $python -ArgumentList 'web_app.py' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/console-info" -TimeoutSec 1
        $info = $response.Content | ConvertFrom-Json
        if ($response.StatusCode -eq 200 -and $info.version -eq 'web-console-20261022.7' -and $info.config_api) {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 250
    }
}

if (-not $ready) {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    throw 'Web console failed to start. Check .venv and dependencies.'
}

$version = [DateTimeOffset]::Now.ToUnixTimeMilliseconds()
$url = "http://127.0.0.1:$Port/?v=$version"
Write-Host "Web console restarted: $url"
Start-Process $url
