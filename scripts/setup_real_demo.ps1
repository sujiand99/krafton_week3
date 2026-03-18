param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$python = if (Get-Command python -ErrorAction SilentlyContinue) {
    (Get-Command python).Source
} elseif (Test-Path $venvPython) {
    $venvPython
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

& $python -m pip install -r (Join-Path $repoRoot "requirements.txt")
Push-Location (Join-Path $repoRoot "frontend")
try {
    $env:Path = "C:\Program Files\nodejs;$env:Path"
    & $npm install
} finally {
    Pop-Location
}

Write-Host "Real demo dependencies are ready." -ForegroundColor Green
Write-Host "Next: run .\scripts\start_real_demo.ps1 from C:\레디스" -ForegroundColor Cyan
