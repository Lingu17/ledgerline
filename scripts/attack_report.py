"""Run the hostile-attempt suite against the simulated bank and write docs/evidence/attacks.json from the real result.

    backend/.venv/Scripts/python scripts/attack_report.py      (Windows)
    backend/.venv/bin/python scripts/attack_report.py          (macOS / Linux)

Nothing here is typed in by hand: the counts come from pytest's own report, the money from the simulated bank's
transfer table before and after each attack (see backend/tests/test_attacks.py). The public /attacks page and the
README badge read the file this writes. Exit code is non-zero if any attack got through.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OUT = ROOT / "docs" / "evidence" / "attacks.json"
BADGE = ROOT / "docs" / "evidence" / "attacks-badge.json"


def main() -> int:
    sys.path.insert(0, str(BACKEND))
    from tests.test_attacks import ATTACKS  # the registry: what each attack tried and which rule stops it

    with tempfile.TemporaryDirectory() as tmp:
        junit, log = Path(tmp) / "attacks.xml", Path(tmp) / "moved.jsonl"
        env = {**os.environ, "LEDGERLINE_ATTACK_LOG": str(log)}
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_attacks.py", f"--junitxml={junit}"]
        proc = subprocess.run(cmd, cwd=BACKEND, env=env)
        cases = {c.get("name"): c for c in ET.parse(junit).getroot().iter("testcase")}
        moved = {}
        if log.exists():
            for line in log.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                moved[row.pop("test")] = row

    attacks, zero = [], {"transfers": 0, "amount_minor": 0, "conversions": 0}
    for name, meta in ATTACKS.items():
        case = cases.get(name)
        passed = case is not None and not any(case.find(t) is not None for t in ("failure", "error", "skipped"))
        m = moved.get(name)
        blocked = passed and m == zero
        attacks.append({"id": name.removeprefix("test_"), **meta, "result": "blocked" if blocked else "NOT BLOCKED",
                        "moved": m})
    total = sum(m["amount_minor"] for m in moved.values()) if moved else None
    # The code that was tested: the last commit that changed the backend or this script (docs-only commits after it
    # do not change what ran, so the page keeps naming the code, not the commit that stores this report).
    full = subprocess.run(["git", "log", "-1", "--format=%H", "--", "backend", "scripts/attack_report.py"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    commit = full[:7]
    report = {
        "what": "Hostile attempts run against the simulated bank (no real money). Each must be refused and move nothing.",
        "how": "backend/tests/test_attacks.py, run by scripts/attack_report.py; money is measured on the simulated bank's own "
               "transfer and conversion records before and after each attempt.",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "commit_full": full,
        "total": len(attacks),
        "blocked": sum(a["result"] == "blocked" for a in attacks),
        "moved_minor_total": total,
        "attacks": attacks,
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ok = report["blocked"] == report["total"] and total == 0
    badge = {"schemaVersion": 1, "label": "attacks blocked",
             "message": f"{report['blocked']}/{report['total']}" + (" · $0 moved" if total == 0 else ""),
             "color": "brightgreen" if ok else "red"}
    BADGE.write_text(json.dumps(badge, ensure_ascii=False) + "\n", encoding="utf-8")  # read by shields.io for the README
    print(f"{report['blocked']}/{report['total']} blocked, moved {total} minor units -> {OUT.relative_to(ROOT)}")
    return 0 if proc.returncode == 0 and report["blocked"] == report["total"] and total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
