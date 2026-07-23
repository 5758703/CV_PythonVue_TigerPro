# Create/refresh backend/.venv (Python 3.12) and install requirements.txt
# Usage: .\scripts\setup_venv.ps1
$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
Set-Location $BackendRoot

$VenvDir = Join-Path $BackendRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Req = Join-Path $BackendRoot "requirements.txt"

Write-Host "==> Checking Python 3.12 ..." -ForegroundColor Cyan
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if (-not $pyLauncher) {
    Write-Host "Python launcher (py) not found. Install Python 3.12 with py launcher." -ForegroundColor Red
    exit 1
}

& py -3.12 -c "import sys; print(sys.version)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.12 not found. RapidOCR 1.4.4 needs Python < 3.13." -ForegroundColor Red
    exit 1
}

if (Test-Path $VenvPython) {
    Write-Host "==> .venv already exists, skip create" -ForegroundColor Yellow
} else {
    Write-Host "==> Creating .venv ..." -ForegroundColor Cyan
    & py -3.12 -m venv $VenvDir
}

Write-Host "==> Upgrading pip ..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip

Write-Host "==> Installing requirements.txt ..." -ForegroundColor Cyan
& $VenvPython -m pip install -r $Req
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install failed" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Done. Start backend with:" -ForegroundColor Green
Write-Host "  .\scripts\run_backend.ps1"
Write-Host "or:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python app.py"
