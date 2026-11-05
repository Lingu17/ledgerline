"""A fault in Ledgerline's own simulated payer agent is a server problem, not the payer's answer.

Seen first on PostgreSQL: a practice company asks its agents in-process, and a signing key that could not be decrypted
(a wrong server secret) came back as an MCP tool error. That error was recorded as the payer's "rejected" answer, which
escalated the payment and blamed the customer. The separate-process path had always raised instead. Both now do."""
from ledgerline.payer_agents import server
from ledgerline.payer_agents.keys import KeyStoreError


def test_a_key_the_agent_cannot_load_records_nothing_and_the_payment_keeps_waiting(client, monkeypatch):
    client.post("/api/demo/step", json={"step": "deposits"})
    before = client.get("/api/deposits/DEP-1005").json()
    assert before["status"] == "awaiting_evidence"

    def broken(_loc):
        raise KeyStoreError("cannot decrypt the signing key for CUST-ACME: wrong LEDGERLINE_SECRET_KEY or tampered row")

    monkeypatch.setattr(server, "load_keys", broken)
    r = client.post("/api/deposits/DEP-1005/ask-agent")
    assert r.status_code == 503 and "not the payer's" in r.json()["detail"]
    after = client.get("/api/deposits/DEP-1005").json()
    assert after["status"] == "awaiting_evidence" and after["evidence"] == before["evidence"] and after["plans"] == before["plans"]

    # Automatic asking leaves it waiting too, to be asked again later.
    from ledgerline import agent_loop

    agent_loop.ask_pending(client.app.state.orgs.get(client.org_id), only="DEP-1005")
    assert client.get("/api/deposits/DEP-1005").json()["status"] == "awaiting_evidence"

    # Once the keys load again, the same payment is answered and verified as usual.
    monkeypatch.undo()
    assert client.post("/api/deposits/DEP-1005/ask-agent").json()["verification"]["verdict"] == "verified"


def test_status_reports_the_transport_each_company_really_uses(tmp_path):
    """The server may run real companies' agents as a separate process; practice companies always ask in-process."""
    from fastapi.testclient import TestClient

    from ledgerline.api.app import create_app
    from ledgerline.config import load_settings

    from .conftest import signup

    app = create_app(load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path), "LEDGERLINE_PAYER_MCP_TRANSPORT": "stdio",
                                    "LEDGERLINE_PROVIDER": "local", "LEDGERLINE_SAMPLE_WORKSPACE": "0", "ANTHROPIC_API_KEY": "",
                                    "AIRWALLEX_CLIENT_ID": "", "AIRWALLEX_API_KEY": "", "AIRWALLEX_WEBHOOK_SECRET": ""}))
    practice, real = TestClient(app), TestClient(app)
    signup(practice, email="p@t.test", org="Practice", start_with="sample")
    signup(real, email="r@t.test", org="Real", start_with="empty")
    assert practice.get("/api/status").json()["payer_agents"]["transport"] == "mcp/in-memory"
    assert real.get("/api/status").json()["payer_agents"]["transport"] == "mcp/stdio"
