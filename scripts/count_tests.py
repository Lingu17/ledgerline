"""Count the tests that exist, from the test runners themselves, and write docs/evidence/tests-badge.json for the README.

    backend/.venv/Scripts/python scripts/count_tests.py

Backend tests are counted by pytest's own collection (the PostgreSQL-only file is included: CI runs it on PostgreSQL);
browser tests by Playwright's --list. Nothing is typed in by hand. Re-run after adding tests.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                         cwd=ROOT / "backend", capture_output=True, text=True).stdout
    m = re.search(r"(\d+) tests? collected", out) or re.search(r"^(\d+) tests?", out, re.M)
    backend = int(m.group(1)) if m else sum(1 for line in out.splitlines() if "::" in line)
    npx = shutil.which("npx") or "npx"
    listed = subprocess.run([npx, "playwright", "test", "--list"], cwd=ROOT / "frontend", capture_output=True, text=True,
                            shell=sys.platform == "win32").stdout
    m = re.search(r"Total: (\d+) tests?", listed)
    browser = int(m.group(1)) if m else 0
    badge = {"schemaVersion": 1, "label": "tests", "message": f"{backend} backend · {browser} browser", "color": "brightgreen"}
    path = ROOT / "docs" / "evidence" / "tests-badge.json"
    path.write_text(json.dumps(badge, ensure_ascii=False) + "\n", encoding="utf-8")
    print(badge["message"], "->", path.relative_to(ROOT))
    return 0 if backend and browser else 1


if __name__ == "__main__":
    raise SystemExit(main())
