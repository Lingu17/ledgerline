"""What any visitor can read: the version and the security contact, and a real security.txt only when the operator set
a contact."""
from fastapi.testclient import TestClient

import pytest

from ledgerline.api.app import create_app
from ledgerline.config import load_settings


def test_without_a_contact_security_txt_is_not_faked(client):
    assert client.get("/api/public/info").json()["security_contact"] is None
    r = client.get("/.well-known/security.txt")
    assert r.status_code == 404 and r.headers["content-type"].startswith("text/plain")


def test_with_a_contact_security_txt_follows_rfc_9116(tmp_path):
    app = create_app(load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path), "LEDGERLINE_SECURITY_CONTACT": "https://example.test/report",
                                    "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory", "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": ""}))
    c = TestClient(app)
    r = c.get("/.well-known/security.txt")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    lines = dict(line.split(": ", 1) for line in r.text.strip().splitlines())
    assert lines["Contact"] == "https://example.test/report" and lines["Expires"].endswith("Z")
    assert lines["Canonical"].endswith("/.well-known/security.txt") and c.get("/api/public/info").json()["security_contact"] == "https://example.test/report"


def test_a_contact_must_be_mailto_or_https(tmp_path):
    with pytest.raises(ValueError, match="mailto: or https://"):
        load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path), "LEDGERLINE_SECURITY_CONTACT": "someone@example.test"})


def test_security_txt_uses_the_configured_origin_not_the_host_header(tmp_path):
    app = create_app(load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path), "LEDGERLINE_SECURITY_CONTACT": "mailto:security@example.test",
                                    "LEDGERLINE_PUBLIC_URL": "https://ledger.example.test", "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
                                    "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": ""}))
    text = TestClient(app).get("/.well-known/security.txt", headers={"Host": "evil.example.test"}).text
    assert "Canonical: https://ledger.example.test/.well-known/security.txt" in text and "evil" not in text


def test_version_commit_and_changelog_are_public(client):
    from ledgerline import __version__, build_commit

    info = client.get("/api/public/info").json()
    assert info["version"] == __version__ and info["commit"] == build_commit()
    assert client.get("/api/health").json()["commit"] == build_commit()
    r = client.get("/api/public/changelog")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown") and r.text.startswith("# Changelog")


def test_a_locked_database_answers_busy_not_500(app, monkeypatch):
    import sqlite3

    from .conftest import new_client

    def locked(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(app.state.control, "signup", locked)
    r = new_client(app).post("/api/auth/signup", json={"email": "busy@example.test", "name": "Busy", "password": "Correct-Horse-42-battery",
                                                       "organization_name": "Busy Co", "start_with": "sample"})
    assert r.status_code == 503 and r.headers["retry-after"] == "2" and "busy" in r.json()["detail"]


def test_a_missing_file_is_a_real_404_and_app_addresses_still_load(client):
    from ledgerline.api.app import FRONTEND_DIST

    if not FRONTEND_DIST.is_dir():  # the page is served only when the frontend is built
        return
    for path in ("/.hg", "/wp-login.php", "/assets/missing.js"):
        assert client.get(path).status_code == 404, path
    assert client.get("/robots.txt").text.startswith("User-agent")
    assert "<!doctype html>" in client.get("/somewhere/in/the/app").text.lower()


def test_a_visitor_session_probe_is_200_not_401(app, client):
    from .conftest import new_client

    visitor = new_client(app).get("/api/auth/session")
    assert visitor.json() == {"signed_in": False} and visitor.headers["cache-control"] == "no-store"
    r = client.get("/api/auth/session")
    me = r.json()
    assert me["signed_in"] is True and me["user"]["email"] == "owner@northbeam.test" and me["csrf_token"]
    assert r.headers["cache-control"] == "no-store"  # it carries the CSRF token


def test_a_deploy_reaches_returning_visitors_and_built_files_are_cached(client):
    from ledgerline.api.app import FRONTEND_DIST

    if not FRONTEND_DIST.is_dir():
        pytest.skip("frontend not built")
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/some/app/address").headers["cache-control"] == "no-cache"
    asset = next((FRONTEND_DIST / "assets").glob("index-*.js")).name
    assert client.get(f"/assets/{asset}").headers["cache-control"] == "public, max-age=31536000, immutable"
    missing = client.get("/assets/index-missing.js")
    assert missing.status_code == 404 and "immutable" not in missing.headers.get("cache-control", "")
    assert client.get("/api/health").headers["cache-control"] == "no-store"


def test_the_public_evidence_page_reads_only_committed_files(client):
    """No sign-in, no live call: the sandbox runs and the outside-agent record come from docs/evidence."""
    from .conftest import new_client
    from ledgerline import REPO_DIR
    import json as _json

    r = new_client(client.app).get("/api/public/evidence")
    assert r.status_code == 200
    body = r.json()
    committed = _json.loads((REPO_DIR / "docs" / "evidence" / "sandbox-runs.json").read_text(encoding="utf-8"))
    assert body["sandbox"] == committed and len(body["sandbox"]["runs"]) >= 8 and body["sandbox"]["simulated_only"]
    assert all(run["proves"] and run["ids"] and run["date"] for run in body["sandbox"]["runs"])
    assert "runs" in body["outside_agent"]  # a placeholder until a real outside run is committed


def test_the_committed_attack_report_matches_the_suite(client):
    """The /attacks page and the README badge read docs/evidence/attacks.json. It must list exactly the attacks in
    tests/test_attacks.py, all blocked with nothing moved, or CI fails and the report must be regenerated."""
    from .conftest import new_client
    from .test_attacks import ATTACKS

    r = new_client(client.app).get("/api/public/attacks").json()
    assert [a["id"] for a in r["attacks"]] == [n.removeprefix("test_") for n in ATTACKS], "run scripts/attack_report.py"
    assert r["total"] == len(ATTACKS) == r["blocked"] and r["moved_minor_total"] == 0
    zero = {"transfers": 0, "amount_minor": 0, "conversions": 0}
    assert all(a["result"] == "blocked" and a["moved"] == zero for a in r["attacks"])
    assert all(a[k] == ATTACKS["test_" + a["id"]][k] for a in r["attacks"] for k in ("category", "tried", "rule"))
    from ledgerline import REPO_DIR
    import json as _json

    badge = _json.loads((REPO_DIR / "docs" / "evidence" / "attacks-badge.json").read_text(encoding="utf-8"))
    assert badge["message"].startswith(f"{r['blocked']}/{r['total']}") and badge["color"] == "brightgreen"


def test_health_reports_whether_the_payer_agents_answer_over_mcp(client, monkeypatch):
    from ledgerline.payer_agents import client as mcp_client

    monkeypatch.setattr(mcp_client, "_probe_state", {"at": None, "result": None, "running": False})
    first = mcp_client.probe_mcp(client.app.state.settings, wait=True)
    assert first["status"] == "ok" and first["memory"] == "ok", first
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["payer_agents_mcp"] == first  # cached: the probe does not start a process each time

    def broken(*_a, **_k):
        raise OSError("no server")
    monkeypatch.setattr(mcp_client, "_probe_state", {"at": None, "result": None, "running": False})
    monkeypatch.setattr(mcp_client.anyio, "run", broken)
    assert mcp_client.probe_mcp(client.app.state.settings, wait=True)["status"] == "unreachable"


def test_the_attack_report_names_the_last_change_to_the_code_it_tested():
    """/attacks says which code it ran on. That must be the newest commit touching the backend or the report script,
    or the report is stale and must be regenerated with scripts/attack_report.py."""
    import json as _json
    import shutil
    import subprocess

    from ledgerline import REPO_DIR

    if not shutil.which("git") or not (REPO_DIR / ".git").exists():
        pytest.skip("not a git checkout")
    shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=REPO_DIR, capture_output=True, text=True).stdout.strip()
    if shallow == "true":
        pytest.skip("shallow clone: history needed (CI checks out with fetch-depth 0)")
    last = subprocess.run(["git", "log", "-1", "--format=%H", "--", "backend", "scripts/attack_report.py"], cwd=REPO_DIR,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "backend", "scripts/attack_report.py"], cwd=REPO_DIR,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        pytest.skip("uncommitted backend changes: commit, then regenerate the report")
    report = _json.loads((REPO_DIR / "docs" / "evidence" / "attacks.json").read_text(encoding="utf-8"))
    assert report["commit_full"] == last and report["commit"] == last[:7], "stale: run scripts/attack_report.py"


def test_the_attacks_page_links_the_ci_run_on_the_live_commit(client, monkeypatch):
    from ledgerline import build_commit, ci_lookup

    from .conftest import new_client

    sha = build_commit(40)
    if not sha:
        pytest.skip("not a git checkout")
    runs = [{"name": "CI", "run_number": 250, "html_url": "https://github.com/Lingu17/ledgerline/actions/runs/1",
             "status": "completed", "conclusion": "success"},
            {"name": "CI", "run_number": 251, "html_url": "https://github.com/Lingu17/ledgerline/actions/runs/2",
             "status": "in_progress", "conclusion": None}]
    monkeypatch.setattr(ci_lookup, "_fetch", lambda s: runs if s == sha else [])
    live = new_client(client.app).get("/api/public/attacks").json()["live"]
    assert live["commit"] == sha[:12] and live["ci"]["run_number"] == 250 and live["ci"]["conclusion"] == "success"

    def down(_s):
        raise OSError("no network")
    monkeypatch.setattr(ci_lookup, "_cache", {})
    monkeypatch.setattr(ci_lookup, "_fetch", down)
    live = new_client(client.app).get("/api/public/attacks").json()["live"]
    assert live["ci"] is None and live["actions_url"].endswith("/actions")
