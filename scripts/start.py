"""Start Ledgerline on http://127.0.0.1:8000 (the API also serves the built UI). Simulated bank, no keys needed.

    python scripts/start.py
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "backend" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not PY.exists():
    sys.exit("Run python scripts/setup.py first.")
print("Ledgerline on http://127.0.0.1:8000  (Ctrl+C to stop)", flush=True)
try:
    sys.exit(subprocess.call([str(PY), "-m", "ledgerline"], cwd=ROOT / "backend"))
except KeyboardInterrupt:
    pass
