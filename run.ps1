# Consilium-Next — dev server on port 8001 (stable root stays on 8000)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt
Write-Host "Consilium-Next -> http://127.0.0.1:8001" -ForegroundColor Cyan
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
