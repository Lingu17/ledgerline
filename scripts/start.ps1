# Start the API (which also serves the built UI) on http://127.0.0.1:8000
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"
.\.venv\Scripts\python -m ledgerline
