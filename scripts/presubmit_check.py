"""Pre-submission check of the live site and the public repository. Read only: it presses nothing and signs in nowhere.

    python scripts/presubmit_check.py                      (defaults below)
    python scripts/presubmit_check.py --site https://... --repo owner/name

Prints one PASS / WARN / FAIL line per check and exits 1 if anything FAILs. WARN never fails the run (for example while
the video link is still the VIDEO_LINK placeholder, or while CI on main is still running).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "ledgerline-presubmit-check", "Accept": "*/*"}
results: list[tuple[str, str, str]] = []


def report(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"{status:<4}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def get(url: str, timeout: float = 15, method: str = "GET") -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=UA, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed or document-listed https URLs
            return r.status, r.read() if method == "GET" else b""
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()


def gh(path: str) -> dict | None:
    status, body = get(f"https://api.github.com{path}")
    return json.loads(body) if status == 200 else None


def links_in(text: str) -> list[str]:
    found = re.findall(r"\]\(([^)\s]+)\)", text) + re.findall(r'(?:href|src)="([^"]+)"', text) + re.findall(r"(?<![(\"])\bhttps://[^\s)<>\"`]+", text)
    return sorted({u.rstrip(".,;") for u in found})


def check_links(doc: Path, site: str, repo: str) -> None:
    text = doc.read_text(encoding="utf-8")
    bad, checked = [], 0
    for url in links_in(text):
        if url == "VIDEO_LINK" or url.startswith(("mailto:", "#")):
            continue
        if url.startswith("http://localhost") or url.startswith("http://127.0.0.1"):
            continue  # local addresses in setup instructions
        if url.startswith("https://") or url.startswith("http://"):
            if "img.shields.io" in url or "/actions/workflows/" in url:
                status, _ = get(url)
            else:
                status, _ = get(url, method="HEAD")
                if status in (403, 405, 0):
                    status, _ = get(url)
            checked += 1
            if not (200 <= status < 400):
                bad.append(f"{url} -> {status}")
        else:
            target = (doc.parent / url.split("#")[0]).resolve()
            checked += 1
            if url.split("#")[0] and not target.exists():
                bad.append(f"{url} -> missing file")
    if bad:
        report("FAIL", f"links in {doc.relative_to(ROOT)}", "; ".join(bad[:6]) + (" …" if len(bad) > 6 else ""))
    else:
        report("PASS", f"links in {doc.relative_to(ROOT)}", f"{checked} checked")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="https://35-207-220-110.sslip.io")
    ap.add_argument("--repo", default="Lingu17/ledgerline")
    a = ap.parse_args()
    site, repo = a.site.rstrip("/"), a.repo

    meta = gh(f"/repos/{repo}")
    if meta is None:
        report("FAIL", "repository is public", "not visible without signing in")
    else:
        report("PASS" if not meta.get("private") else "FAIL", "repository is public")
    main_sha = (gh(f"/repos/{repo}/commits/main") or {}).get("sha")

    status, body = get(f"{site}/api/health")
    health = json.loads(body) if status == 200 else {}
    report("PASS" if health.get("status") == "ok" else "FAIL", "/api/health ok", f"HTTP {status}")
    live = health.get("commit")
    if live and main_sha:
        report("PASS" if main_sha.startswith(live) else "FAIL", "deployed commit equals main", f"live {live}, main {main_sha[:12]}")
    else:
        report("FAIL", "deployed commit equals main", f"live {live}, main {main_sha}")
    mcp = (health.get("payer_agents_mcp") or {}).get("status")
    report("PASS" if mcp == "ok" else "WARN", "payer agents answer over MCP", str(mcp))

    for path in ("/", "/evidence", "/attacks"):
        s, _ = get(site + path)
        report("PASS" if s == 200 else "FAIL", f"{path} returns 200", f"HTTP {s}")

    s, html = get(site + "/")
    scripts = re.findall(rb'src="(/assets/[^"]+\.js)"', html)
    has_button = any(b"Judge demo \xe2\x80\x94 one click" in get(site + src.decode())[1] for src in scripts)
    report("PASS" if has_button else "FAIL", "judge demo button is in the page (not pressed)")

    s, body = get(f"{site}/api/public/attacks")
    att = json.loads(body) if s == 200 else {}
    ok = att.get("total") and att.get("blocked") == att.get("total") and att.get("moved_minor_total") == 0
    report("PASS" if ok else "FAIL", "/attacks report all blocked, $0 moved", f"{att.get('blocked')}/{att.get('total')}")

    runs = (gh(f"/repos/{repo}/actions/runs?branch=main&per_page=5") or {}).get("workflow_runs", [])
    run = next((r for r in runs if r.get("head_sha") == main_sha), None)
    if run is None:
        report("WARN", "CI on main", "no run found for the main commit yet")
    elif run["status"] != "completed":
        report("WARN", "CI on main", f"run #{run['run_number']} still {run['status']}")
    else:
        report("PASS" if run["conclusion"] == "success" else "FAIL", "CI on main is green", f"run #{run['run_number']} {run['conclusion']}")

    for doc in (ROOT / "README.md", ROOT / "docs" / "SUBMISSION.md"):
        check_links(doc, site, repo)
    left = [str(d.relative_to(ROOT)) for d in (ROOT / "README.md", ROOT / "docs" / "SUBMISSION.md") if "VIDEO_LINK" in d.read_text(encoding="utf-8")]
    report("WARN" if left else "PASS", "video link filled in", ("VIDEO_LINK still in " + ", ".join(left)) if left else "")

    fails = sum(1 for r in results if r[0] == "FAIL")
    warns = sum(1 for r in results if r[0] == "WARN")
    print(f"\n{len(results) - fails - warns} PASS · {warns} WARN · {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
