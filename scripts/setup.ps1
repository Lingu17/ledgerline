# One-time setup on Windows (PowerShell). Requires Python 3.12+ and Node 20+ on PATH.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
Set-Location "$root\frontend"
npm ci
npm run build
Write-Host "Setup complete. Start with: powershell -ExecutionPolicy Bypass -File scripts\start.ps1"
