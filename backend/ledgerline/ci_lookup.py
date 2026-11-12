"""Which GitHub Actions run tested a commit, for the public /attacks page. Read from GitHub's public API, never typed in.

Cached for ten minutes (a failed lookup for two), with a short timeout, so the page never waits long and GitHub's
unauthenticated rate limit is never reached. Returns None when it cannot tell; the page then links to the Actions list.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Any

REPO = "Lingu17/ledgerline"
ACTIONS_URL = f"https://github.com/{REPO}/actions"
_TTL_OK, _TTL_FAIL = 600.0, 120.0
_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def _fetch(sha: str) -> list[dict[str, Any]]:
    url = f"https://api.github.com/repos/{REPO}/actions/runs?head_sha={sha}&per_page=10"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "ledgerline-attacks-page"})
    with urllib.request.urlopen(req, timeout=3) as r:  # noqa: S310 - fixed https URL
        return json.loads(r.read().decode("utf-8")).get("workflow_runs", [])


def run_for(sha: str | None) -> dict[str, Any] | None:
    """The CI workflow run on this exact commit: the latest completed one, else the latest in progress."""
    if not sha or len(sha) != 40:
        return None
    now = time.monotonic()
    with _lock:
        hit = _cache.get(sha)
        if hit and now - hit[0] < (_TTL_OK if hit[1] else _TTL_FAIL):
            return hit[1]
    try:
        runs = [r for r in _fetch(sha) if r.get("name") == "CI" or str(r.get("path", "")).endswith("ci.yml")]
        runs.sort(key=lambda r: (r.get("status") == "completed", r.get("run_number", 0)), reverse=True)
        best = runs[0] if runs else None
        out = None if best is None else {"run_number": best["run_number"], "url": best["html_url"], "status": best["status"],
                                         "conclusion": best.get("conclusion"), "sha": sha}
    except Exception:  # noqa: BLE001 - the page shows a plain link instead
        out = None
    with _lock:
        _cache[sha] = (now, out)
    return out
