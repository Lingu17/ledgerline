"""Deployment behaviour: health check, PORT, proxy-aware client address, persistent-storage guard."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ledgerline.api.app import create_app
from ledgerline.config import load_settings

from .conftest import PASSWORD, signup


def _settings(tmp_path, **extra):
    return load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path / "data"), "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
                          "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": "", "ANTHROPIC_API_KEY": "", **extra})


def test_health_reports_ready_without_auth(tmp_path):
    c = TestClient(create_app(_settings(tmp_path)))
    r = c.get("/api/health")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["status"] == "ok" and body["control_schema"] == 2 and body["storage"] == "local directory"
    assert not any(":\\" in str(v) or str(v).startswith("/") for v in body.values())  # never reveals filesystem paths


def test_port_env_is_used_when_ledgerline_port_is_unset(tmp_path):
    assert _settings(tmp_path, PORT="10000", LEDGERLINE_PORT="").port == 10000
    assert _settings(tmp_path, PORT="10000", LEDGERLINE_PORT="8123").port == 8123


def test_refuses_to_start_when_data_dir_is_not_on_the_persistent_mount(tmp_path):
    (tmp_path / "not-a-mount").mkdir()
    with pytest.raises(RuntimeError, match="persistent mount"):
        create_app(_settings(tmp_path, LEDGERLINE_REQUIRE_PERSISTENT_MOUNT=str(tmp_path / "not-a-mount")))


def _fail_logins(c, ip_chain, n, email="victim@northbeam.test"):
    codes = []
    for _ in range(n):
        codes.append(c.post("/api/auth/login", json={"email": email, "password": "wrong-password-123"},
                            headers={"X-Forwarded-For": ip_chain}).status_code)
    return codes


def test_throttling_uses_the_real_client_behind_two_proxies(tmp_path):
    """Behind Vercel -> Render, every request arrives from a proxy. Without proxy awareness one judge's
    typos would lock out every judge; with it, each browser has its own budget and spoofing is ignored."""
    app = create_app(_settings(tmp_path, LEDGERLINE_TRUSTED_PROXY_HOPS="2"))
    c = TestClient(app)
    # Attacker at 203.0.113.9 burns its budget on many accounts (per-IP key).
    for i in range(5):
        _fail_logins(c, "203.0.113.9, 76.76.21.21", 1, email=f"user{i}@northbeam.test")
    assert _fail_logins(c, "203.0.113.9, 76.76.21.21", 1, email="other@northbeam.test") == [429]
    # Prepending a forged address does not give a fresh budget: the client is read from the trusted end.
    assert _fail_logins(c, "198.51.100.1, 203.0.113.9, 76.76.21.21", 1, email="other2@northbeam.test") == [429]
    # A different judge behind the same proxy is unaffected.
    owner = TestClient(app)
    signup(owner, email="judge@northbeam.test")
    r = owner.post("/api/auth/login", json={"email": "judge@northbeam.test", "password": PASSWORD},
                   headers={"X-Forwarded-For": "192.0.2.44, 76.76.21.21"})
    assert r.status_code == 200, r.text


def test_forwarded_header_is_ignored_without_trusted_proxies(tmp_path):
    c = TestClient(create_app(_settings(tmp_path)))
    for i in range(5):
        _fail_logins(c, f"10.0.0.{i}", 1, email=f"u{i}@northbeam.test")
    # Varying X-Forwarded-For does not escape the per-address budget when no proxy is trusted.
    assert _fail_logins(c, "10.9.9.9", 1, email="fresh@northbeam.test") == [429]


def _ip_of(app, headers):
    from starlette.requests import Request

    from ledgerline.api.security import client_ip

    scope = {"type": "http", "app": app, "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
             "client": ("10.0.0.5", 1234), "method": "GET", "path": "/"}
    return client_ip(Request(scope))


def test_short_forwarded_chain_fails_closed(tmp_path):
    """Codex review finding 1: a direct client must not choose its identity by sending a short X-Forwarded-For."""
    app = create_app(_settings(tmp_path, LEDGERLINE_TRUSTED_PROXY_HOPS="2"))
    assert _ip_of(app, {"X-Forwarded-For": "client, edge"}) == "client"
    assert _ip_of(app, {"X-Forwarded-For": "forged"}) == "10.0.0.5"  # too short: never the leftmost, client-chosen entry
    assert _ip_of(app, {}) == "10.0.0.5"


def test_edge_secret_gates_forwarded_header_trust(tmp_path):
    app = create_app(_settings(tmp_path, LEDGERLINE_TRUSTED_PROXY_HOPS="2", LEDGERLINE_EDGE_SECRET="edge-test-secret"))
    assert _ip_of(app, {"X-Forwarded-For": "client, edge", "X-Ledgerline-Edge": "edge-test-secret"}) == "client"
    assert _ip_of(app, {"X-Forwarded-For": "forged, edge"}) == "10.0.0.5"
    assert _ip_of(app, {"X-Forwarded-For": "forged, edge", "X-Ledgerline-Edge": "wrong"}) == "10.0.0.5"


def test_withdrawn_sandbox_access_applies_to_cached_contexts(tmp_path):
    """Codex review finding 5: revocation takes effect at use time, without an explicit cache invalidation."""
    app = create_app(_settings(tmp_path, AIRWALLEX_CLIENT_ID="cid", AIRWALLEX_API_KEY="key"))
    c = TestClient(app)
    signup(c, email="ops@deploy.test", start_with="empty")
    app.state.settings.sandbox_org_ids = frozenset({c.org_id})
    assert c.put("/api/organization", json={"bank_mode": "airwallex_sandbox"}).status_code == 200
    assert app.state.orgs.get(c.org_id).sandbox is not None
    app.state.settings.sandbox_org_ids = frozenset()
    assert c.get("/api/deposits").status_code == 403


def test_hosted_mode_refuses_to_start_without_a_database(tmp_path):
    with pytest.raises(ValueError, match="refusing to start on local storage"):
        _settings(tmp_path, LEDGERLINE_REQUIRE_DATABASE="1", LEDGERLINE_DATABASE_URL="")


def test_edge_header_placeholder_is_not_a_valid_secret(tmp_path):
    """Before the Vercel variable exists, Vercel sends the literal "$LEDGERLINE_EDGE_SECRET": never accepted."""
    app = create_app(_settings(tmp_path, LEDGERLINE_TRUSTED_PROXY_HOPS="4", LEDGERLINE_EDGE_SECRET="real-edge-secret-0123456789abcdef"))
    chain = "client, vercel, cf, lb"
    assert _ip_of(app, {"X-Forwarded-For": chain, "X-Ledgerline-Edge": "$LEDGERLINE_EDGE_SECRET"}) == "10.0.0.5"
    assert _ip_of(app, {"X-Forwarded-For": chain, "X-Ledgerline-Edge": "real-edge-secret-0123456789abcdef"}) == "client"
    # Direct caller forging one extra entry, without the secret: not trusted.
    assert _ip_of(app, {"X-Forwarded-For": "forged, me, cf, lb"}) == "10.0.0.5"
