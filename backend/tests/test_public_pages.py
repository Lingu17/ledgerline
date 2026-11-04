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
