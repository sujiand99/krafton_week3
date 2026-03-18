param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) {
    $venvPython
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    (Get-Command python).Source
} else {
    throw "Python was not found. Activate .venv or install Python first."
}

$npm = if (Test-Path "C:\Program Files\nodejs\npm.cmd") {
    "C:\Program Files\nodejs\npm.cmd"
} elseif (Get-Command npm.cmd -ErrorAction SilentlyContinue) {
    (Get-Command npm.cmd).Source
} elseif (Get-Command npm -ErrorAction SilentlyContinue) {
    (Get-Command npm).Source
} else {
    throw "npm was not found. Install Node.js first."
}

@"
VITE_API_MODE=real
VITE_APP_SERVER_BASE_URL=/api
VITE_DB_API_BASE_URL=/db-api
VITE_POLL_INTERVAL_MS=1000
VITE_DEFAULT_HOLD_SECONDS=15
"@ | Set-Content -Path (Join-Path $repoRoot "frontend\.env.local") -Encoding utf8

function Start-RealWindow {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$Command,
        [string]$WorkingDirectory = $repoRoot
    )

    Start-Process -FilePath "C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" -WorkingDirectory $WorkingDirectory -ArgumentList @("-NoExit", "-Command", $Command) -WindowStyle Normal | Out-Null
}

$redisCommand = @"
Set-Location '$repoRoot'
& '$python' -m server.server --db-path data/mini_redis.db --snapshot-interval 5
"@

$dbCommand = @"
Set-Location '$repoRoot'
& '$python' -m uvicorn ticketing_api.app:app --host 127.0.0.1 --port 8001
"@

$appCommand = @"
Set-Location '$repoRoot'
& '$python' -m uvicorn app_server.app:app --host 127.0.0.1 --port 8000
"@

$frontendCommand = @"
`$env:Path = 'C:\Program Files\nodejs;' + `$env:Path
Set-Location '$repoRoot\frontend'
& '$npm' run dev -- --host 127.0.0.1
"@

Start-RealWindow -Title "Mini Redis" -Command $redisCommand
Start-Sleep -Milliseconds 500
Start-RealWindow -Title "Ticketing DB API" -Command $dbCommand
Start-Sleep -Milliseconds 500
Start-RealWindow -Title "Ticketing App Server" -Command $appCommand
Start-Sleep -Milliseconds 500
Start-RealWindow -Title "Ticketing Frontend" -Command $frontendCommand -WorkingDirectory (Join-Path $repoRoot "frontend")

Write-Host "Real demo services are starting..." -ForegroundColor Green
Write-Host "Frontend: http://127.0.0.1:5173/ (or the next free Vite port if 5173 is busy)" -ForegroundColor Cyan
Write-Host "App Server: http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "DB API: http://127.0.0.1:8001" -ForegroundColor Cyan
