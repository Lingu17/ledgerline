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
