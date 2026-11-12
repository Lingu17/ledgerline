"""One-time setup on any OS: a virtual environment with the locked backend packages, then the built frontend.

    python scripts/setup.py          (Python 3.13+ and Node 22.12+ on PATH)
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / "backend" / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd, cwd):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True, shell=os.name == "nt" and cmd[0] == "npm")


if sys.version_info < (3, 13):
    sys.exit(f"Python 3.13+ is needed (this is {sys.version.split()[0]}).")
if not shutil.which("npm"):
    sys.exit("Node 22.12+ with npm is needed on PATH.")
if not PY.exists():
    run([sys.executable, "-m", "venv", str(VENV)], ROOT)
run([str(PY), "-m", "pip", "install", "--require-hashes", "-r", "requirements-lock.txt"], ROOT / "backend")
run(["npm", "ci"], ROOT / "frontend")
run(["npm", "run", "build"], ROOT / "frontend")
print("\nSetup complete. Start with: python scripts/start.py")
