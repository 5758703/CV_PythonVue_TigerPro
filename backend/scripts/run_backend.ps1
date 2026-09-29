# Start backend with backend/.venv (Python 3.12)
# Falls back to legacy .venv312 or currently activated python (conda/venv)
$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
Set-Location $BackendRoot

function Resolve-BackendPython {
    $candidates = @(
        (Join-Path $BackendRoot ".venv\Scripts\python.exe"),
        (Join-Path $BackendRoot ".venv312\Scripts\python.exe")
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }
    $active = Get-Command python -ErrorAction SilentlyContinue
    if ($active) {
        & $active.Source -c "import flask" 2>$null
        if ($LASTEXITCODE -eq 0) { return $active.Source }
    }
    return $null
}

$VenvPython = Resolve-BackendPython
if (-not $VenvPython) {
    Write-Host "No usable backend Python found." -ForegroundColor Yellow
    Write-Host "Create venv first:"
    Write-Host "  cd backend"
    Write-Host "  .\scripts\setup_venv.ps1"
    Write-Host ""
    Write-Host "Or use conda:"
    Write-Host "  conda activate cv_python_tigerpro"
    Write-Host "  python app.py"
    exit 1
}

Write-Host "Using: $VenvPython" -ForegroundColor DarkGray
# Initialize schema before the two processes start; the worker needs the job table.
& $VenvPython -c "from app import app"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$Worker = Start-Process -FilePath $VenvPython -ArgumentList "scripts/admin_job_worker.py" -WorkingDirectory $BackendRoot -WindowStyle Hidden -PassThru
Write-Host "Management worker PID: $($Worker.Id)" -ForegroundColor DarkGray
try {
    & $VenvPython app.py
} finally {
    if (-not $Worker.HasExited) { Stop-Process -Id $Worker.Id }
}
