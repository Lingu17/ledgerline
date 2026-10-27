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
