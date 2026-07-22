# 使用 Python 3.12 虚拟环境启动后端（推荐：RapidOCR 1.4.4 需 Python <3.13）
$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $BackendRoot ".venv312\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "未找到 $VenvPython" -ForegroundColor Yellow
    Write-Host "请先创建环境："
    Write-Host "  cd backend"
    Write-Host "  py -3.12 -m venv .venv312"
    Write-Host "  .\.venv312\Scripts\pip install -r requirements.txt"
    exit 1
}

Set-Location $BackendRoot
& $VenvPython app.py
