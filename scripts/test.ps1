# Backend tests + frontend typecheck/build
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"
.\.venv\Scripts\python -m pytest -q
Set-Location "$root\frontend"
npm run build
