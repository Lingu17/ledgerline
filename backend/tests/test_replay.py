"""Replay this decision: the rules, run again on the inputs stored with a plan, give the same plan; a changed input or
plan is caught; replaying changes nothing."""
import json

import pytest
from fastapi.testclient import TestClient

from ledgerline import db
from ledgerline.api.app import create_app
from ledgerline.config import load_settings

from .conftest import signup


def replays(c, dep):
    return [c.get(f"/api/deposits/{dep}/plans/{p['version']}/replay").json() for p in c.get(f"/api/deposits/{dep}").json()["plans"]]


def everything(c):
    return {"deposits": c.get("/api/deposits").json(), "audit": c.get("/api/audit", params={"limit": 1}).headers["x-total-count"],
            "approvals": c.get("/api/approvals").json(), "operations": c.get("/api/operations").json()}


def test_every_rules_decision_in_the_practice_company_replays_to_the_same_plan(client):
    for step in ("deposits", "links", "agents"):
        assert client.post("/api/demo/step", json={"step": step}).status_code == 200
    before = everything(client)
    seen = set()
    for d in client.get("/api/deposits").json():
        for r in replays(client, d["id"]):
            assert r["replayable"] and r["ok"], r
            seen.add(r["rule"])
    assert seen == {"initial_plan", "payer_agent_answer"}
    assert everything(client) == before  # read-only


def test_the_advance_that_dropped_a_refund_replays_with_its_three_checks(client):
    client.post("/api/demo/step", json={"step": "deposits"})
    client.post("/api/deposits/DEP-1005/ask-agent")
    r = replays(client, "DEP-1005")[-1]
    assert r["ok"] and r["recomputed"]["verdict"] == "verified"
    assert r["recomputed"]["checks"] == [{"signature": True}, {"binding": True}, {"records": True}]
    assert r["recomputed"]["plan"]["category"] == "verified_advance_credit"


def test_a_changed_input_or_plan_is_caught(client, app):
    client.post("/api/demo/step", json={"step": "deposits"})
    ctx = app.state.orgs.get(client.org_id)
    with ctx.conn() as conn, db.transaction(conn):
        inputs = json.loads(db.row(conn, "SELECT inputs FROM plans WHERE deposit_id = 'DEP-1001' AND version = 1")["inputs"])
        inputs["deposit"]["amount_minor"] += 1
        conn.execute("UPDATE plans SET inputs = ? WHERE deposit_id = 'DEP-1001' AND version = 1", (json.dumps(inputs),))
        conn.execute("UPDATE plans SET category = 'unidentified_payer' WHERE deposit_id = 'DEP-1002' AND version = 1")
    edited = client.get("/api/deposits/DEP-1001/plans/1/replay").json()
    assert edited["inputs_untampered"] is False and edited["ok"] is False
    relabelled = client.get("/api/deposits/DEP-1002/plans/1/replay").json()
    assert relabelled["inputs_untampered"] and not relabelled["identical"]
    assert any(d.startswith("category: stored \"unidentified_payer\"") for d in relabelled["differences"])


def test_a_persons_decision_is_not_replayed_and_unknown_plans_are_404(client):
    for step in ("deposits", "links", "agents"):
        client.post("/api/demo/step", json={"step": step})
    r = client.post("/api/deposits/DEP-1004/resolve", json={"action": "credit", "amount": "100.00", "note": "Agreed by phone"})
    assert r.status_code == 200, r.text
    last = replays(client, "DEP-1004")[-1]
    assert last["kind"] == "operator" and not last["replayable"] and "person" in last["reason"]
    assert client.get("/api/deposits/DEP-1004/plans/99/replay").status_code == 404


def test_an_answer_with_a_float_is_recorded_and_replays(client, app):
    from ledgerline.reconcile import record_agent_answer

    client.post("/api/demo/step", json={"step": "deposits"})
    ctx = app.state.orgs.get(client.org_id)
    answer = {"status": "answered", "envelope": {"claim": {"amount_minor": 1200.5}, "signature": "x", "key_id": "y"}}
    with ctx.conn() as conn, db.transaction(conn):
        record_agent_answer(conn, ctx, "DEP-1005", "CUST-DUNMORE", answer, "mcp/test")
    r = replays(client, "DEP-1005")[-1]
    assert r["ok"] and r["recomputed"]["verdict"] == "rejected"


@pytest.fixture
def harness_app(tmp_path):
    return create_app(load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path), "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
                                     "LEDGERLINE_SIGNUP_PER_IP_HOUR": "100000", "LEDGERLINE_SIGNUP_PER_IP_DAY": "100000",
                                     "LEDGERLINE_SIGNUP_PER_DAY": "100000", "ANTHROPIC_API_KEY": "", "GOOGLE_CLIENT_ID": "",
                                     "APPLE_CLIENT_ID": ""}))


@pytest.mark.parametrize("seed", [3, 17])
def test_every_rules_decision_in_a_synthetic_company_replays_to_the_same_plan(harness_app, seed):
    from .accuracy_harness import Scenario

    s = Scenario(harness_app, seed)
    s.run()
    kinds = set()
    for dep in s.m.deposits:
        for r in replays(s.c, dep):
            kinds.add(r["kind"])
            assert r["ok"] if r["replayable"] else r["kind"] == "operator", r
    assert "initial" in kinds


def test_a_real_company_can_replay_too(app):
    c = TestClient(app)
    signup(c, email="replay@real.test", start_with="empty")
    c.post("/api/customers", json={"name": "Acme", "country": "GB", "payer_names": ["ACME LTD"], "refund_beneficiary": "Acme - account"})
    c.post("/api/payments", json={"external_ref": "R-1", "currency": "GBP", "amount": "10.00", "payer_name": "ACME LTD", "reference": ""})
    dep = c.get("/api/deposits").json()[0]["id"]
    assert replays(c, dep)[0]["ok"]
