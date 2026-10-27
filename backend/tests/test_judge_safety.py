"""Public judges each own an organization. Shared server credentials must not become theirs:
the Airwallex sandbox account is reserved for allow-listed organizations, and the shared Claude
key is rate-limited per organization with its output validated before use."""
from __future__ import annotations

from fastapi.testclient import TestClient

from ledgerline import claude_reader
from ledgerline.api.app import create_app
from ledgerline.config import load_settings

from .conftest import signup

CREDS = {"AIRWALLEX_CLIENT_ID": "cid-test", "AIRWALLEX_API_KEY": "key-test"}


def _app(tmp_path, **extra):
    return create_app(load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path / "d"), "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
                                     "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": "", "ANTHROPIC_API_KEY": "", **extra}))


def test_judge_organization_cannot_use_the_shared_sandbox_account(tmp_path):
    app = _app(tmp_path, **CREDS)
    judge = TestClient(app)
    signup(judge, email="judge@deploy.test", start_with="empty")
    org = judge.get("/api/organization").json()
    assert org["server"]["airwallex_credentials_present"] and not org["server"]["sandbox_allowed"]
    r = judge.put("/api/organization", json={"bank_mode": "airwallex_sandbox"})
    assert r.status_code == 422 and judge.get("/api/organization").json()["bank_mode"] == "local"
    # The readiness check must not reveal the shared account's ids or balances to a judge.
    chk = judge.post("/api/integrations/check").json()["airwallex"]
    assert chk["status"] == "restricted" and "global_accounts" not in chk


def test_allow_listed_organization_may_switch_and_others_stay_blocked(tmp_path):
    app = _app(tmp_path, **CREDS)
    ops = TestClient(app)
    signup(ops, email="ops@deploy.test", start_with="empty")
    app.state.settings.sandbox_org_ids = frozenset({ops.org_id})
    assert ops.get("/api/organization").json()["server"]["sandbox_allowed"]
    assert ops.put("/api/organization", json={"bank_mode": "airwallex_sandbox"}).status_code == 200
    # If the operator later withdraws the allow-listing, the organization is refused rather than using the account.
    app.state.settings.sandbox_org_ids = frozenset()
    app.state.orgs.invalidate(ops.org_id)
    assert ops.get("/api/deposits").status_code == 403


def test_model_output_is_validated_against_the_tool_schema():
    ok = {"tool": "propose_customer_credit", "input": {"for_invoice_id": "INV-2244", "rationale": "advance"}, "model": "m"}
    assert claude_reader.typed_proposal(ok) == ok
    bad = [
        {"tool": "transfer_money", "input": {"amount": "1"}},
        {"tool": "propose_invoice_match", "input": {"invoice_id": "INV-1; DROP", "paid_on_behalf_of": "", "rationale": "x"}},
        {"tool": "propose_invoice_match", "input": {"invoice_id": "INV-2231", "rationale": "missing field"}},
        {"tool": "propose_refund", "input": {"rationale": 5}},
        {"tool": "propose_customer_credit", "input": {"for_invoice_id": "2244", "rationale": "x"}},
    ]
    for b in bad:
        assert claude_reader.typed_proposal(b)["tool"] == "escalate", b


def test_claude_reads_are_capped_per_organization_per_day(tmp_path, monkeypatch):
    app = _app(tmp_path, ANTHROPIC_API_KEY="sk-test-not-real", LEDGERLINE_CLAUDE_DAILY_LIMIT="2")
    calls = []

    def fake(ctx, text):
        calls.append(text)
        return {"tool": "escalate", "input": {"reason": "fake"}, "model": "fake-model"}

    monkeypatch.setattr(claude_reader, "_claude_read", fake)
    c = TestClient(app)
    signup(c, email="cap@deploy.test", start_with="sample")
    body = {"text": "Payment for invoice INV-2244, thanks"}
    assert c.post("/api/deposits/DEP-1004/read-remittance", json=body).status_code == 200
    assert c.post("/api/deposits/DEP-1004/read-remittance", json=body).status_code == 200
    r = c.post("/api/deposits/DEP-1004/read-remittance", json=body)
    assert r.status_code == 409 and "Claude reads for today" in r.json()["detail"]
    assert len(calls) == 2
    # Another judge's organization has its own budget.
    other = TestClient(app)
    signup(other, email="cap2@deploy.test", org="Other", start_with="sample")
    assert other.post("/api/deposits/DEP-1004/read-remittance", json=body).status_code == 200


def _claude_org(tmp_path, monkeypatch, fake, **limits):
    app = _app(tmp_path, ANTHROPIC_API_KEY="sk-test-not-real", **limits)
    monkeypatch.setattr(claude_reader, "_claude_read", fake)
    c = TestClient(app)
    signup(c, email="race@deploy.test", start_with="sample")
    return app, c


def test_simultaneous_claude_reads_cannot_exceed_the_budget(tmp_path, monkeypatch):
    import threading
    import time

    calls = []

    def fake(ctx, text):
        calls.append(text)
        time.sleep(0.2)  # keep the call in flight while the other requests arrive
        return {"tool": "escalate", "input": {"reason": "fake"}, "model": "fake-model"}

    app, c = _claude_org(tmp_path, monkeypatch, fake, LEDGERLINE_CLAUDE_DAILY_LIMIT="1")
    ctx, control = app.state.orgs.get(c.org_id), app.state.control
    results: list[str] = []
    start = threading.Barrier(6)

    def worker():
        start.wait()
        try:
            claude_reader.read_remittance(ctx, "DEP-1004", "race", "Payment for invoice INV-2244, thanks", control=control)
            results.append("ok")
        except ValueError as exc:
            results.append(str(exc))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and results.count("ok") == 1
    assert sum("Claude reads for today" in r for r in results) == 5


def test_failed_claude_calls_consume_the_budget(tmp_path, monkeypatch):
    calls = []

    def failing(ctx, text):
        calls.append(text)
        raise TimeoutError("provider did not answer")

    app, c = _claude_org(tmp_path, monkeypatch, failing, LEDGERLINE_CLAUDE_DAILY_LIMIT="2")
    body = {"text": "Payment for invoice INV-2244, thanks"}
    for _ in range(2):
        assert c.post("/api/deposits/DEP-1004/read-remittance", json=body).status_code == 502
    r = c.post("/api/deposits/DEP-1004/read-remittance", json=body)
    assert r.status_code == 409 and "Claude reads for today" in r.json()["detail"]
    assert len(calls) == 2
    with app.state.control.conn() as conn:
        statuses = [row[0] for row in conn.execute("SELECT status FROM claude_calls ORDER BY id")]
    assert statuses == ["failed", "failed"]


def test_server_wide_claude_budget_applies_across_organizations(tmp_path, monkeypatch):
    calls = []

    def fake(ctx, text):
        calls.append(text)
        return {"tool": "escalate", "input": {"reason": "fake"}, "model": "fake-model"}

    app, a = _claude_org(tmp_path, monkeypatch, fake, LEDGERLINE_CLAUDE_DAILY_LIMIT="5",
                         LEDGERLINE_CLAUDE_SERVER_DAILY_LIMIT="2")
    b = TestClient(app)
    signup(b, email="race2@deploy.test", org="Second", start_with="sample")
    body = {"text": "Payment for invoice INV-2244, thanks"}
    assert a.post("/api/deposits/DEP-1004/read-remittance", json=body).status_code == 200
    assert b.post("/api/deposits/DEP-1004/read-remittance", json=body).status_code == 200
    r = a.post("/api/deposits/DEP-1004/read-remittance", json=body)
    assert r.status_code == 409 and "server has reached its daily Claude budget" in r.json()["detail"]
    assert len(calls) == 2
