"""The "why this plan" explanation: advice only, cites real ids, uses only the facts' numbers, respects the budget."""
import pytest
from fastapi.testclient import TestClient

from ledgerline import explain
from ledgerline.api.app import create_app
from ledgerline.config import load_settings

from .conftest import signup


def snapshot(c, dep):
    d = c.get(f"/api/deposits/{dep}").json()
    return {"status": d["status"], "plans": d["plans"], "approvals": c.get("/api/approvals").json(), "operations": c.get("/api/operations").json()}


def test_practice_explanation_cites_only_real_ids_and_changes_nothing(client):
    client.post("/api/demo/step", json={"step": "deposits"})
    client.post("/api/deposits/DEP-1005/ask-agent")
    before = snapshot(client, "DEP-1005")
    r = client.post("/api/deposits/DEP-1005/explanation").json()["explanation"]
    assert r["available"] and r["label"] == explain.LABEL_FIXTURE and 1 <= len(r["sentences"]) <= 4
    assert "DEP-1005" in r["cited_ids"] and "EV-DEP-1005-1" in r["cited_ids"]
    assert snapshot(client, "DEP-1005") == before  # the decision is the same with or without an explanation
    assert client.get("/api/deposits/DEP-1005/explanation").json()["explanation"] == r  # cached per plan version


@pytest.fixture
def claude_app(tmp_path):
    return create_app(load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path), "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
                                    "ANTHROPIC_API_KEY": "sk-test-not-real", "LEDGERLINE_CLAUDE_DAILY_LIMIT": "2",
                                    "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": ""}))


def real_company(app, monkeypatch, answer):
    """A real (non-practice) company with the practice data, and a fake Claude that returns `answer`."""
    from ledgerline.demo import run_step

    calls = []

    def fake(ctx, f):
        calls.append(f)
        return answer(f)
    monkeypatch.setattr(explain, "_claude", fake)
    c = TestClient(app)
    signup(c, email="why@test.example", start_with="empty")
    ctx = app.state.orgs.get(c.org_id)
    run_step(ctx, "seed", "t")
    for s in ("deposits", "links", "agents"):
        run_step(ctx, s, "t")
    return c, calls


def test_claude_text_with_a_number_not_in_the_facts_is_dropped(claude_app, monkeypatch):
    c, _ = real_company(claude_app, monkeypatch, lambda f: {"sentences": [f"{f['deposit']['id']} should be refunded 9,999.00 now."],
                                                             "cited_ids": [f["deposit"]["id"]]})
    r = c.post("/api/deposits/DEP-1005/explanation").json()["explanation"]
    assert r["available"] is False and "9999" in r["reason"]


def test_claude_text_citing_an_unknown_id_is_dropped(claude_app, monkeypatch):
    c, _ = real_company(claude_app, monkeypatch, lambda f: {"sentences": ["It matches the invoice."], "cited_ids": ["INV-0001"]})
    r = c.post("/api/deposits/DEP-1005/explanation").json()["explanation"]
    assert r["available"] is False and "do not exist" in r["reason"]


def test_a_good_claude_explanation_is_kept_labelled_and_cached(claude_app, monkeypatch):
    def good(f):
        return {"sentences": [f"{f['deposit']['id']} for {f['deposit']['amount']} {f['deposit']['currency']} was confirmed as an advance by "
                              f"{f['evidence'][-1]['id']}, which passed {f['evidence'][-1]['checks_passed']} of 3 checks."],
                "cited_ids": [f["deposit"]["id"], f["evidence"][-1]["id"]]}
    c, calls = real_company(claude_app, monkeypatch, good)
    before = snapshot(c, "DEP-1005")
    r = c.post("/api/deposits/DEP-1005/explanation").json()["explanation"]
    assert r["available"] and r["label"] == explain.LABEL_CLAUDE
    c.post("/api/deposits/DEP-1005/explanation")
    assert len(calls) == 1  # cached for this plan version: no second call
    assert snapshot(c, "DEP-1005") == before
    assert "remittance" not in str(calls[0]).lower() or "document" not in calls[0]  # facts only, no email text


def test_the_daily_budget_is_respected(claude_app, monkeypatch):
    c, calls = real_company(claude_app, monkeypatch, lambda f: {"sentences": ["ok"], "cited_ids": []})
    assert c.post("/api/deposits/DEP-1004/explanation").status_code == 200
    assert c.post("/api/deposits/DEP-1005/explanation").status_code == 200
    r = c.post("/api/deposits/DEP-1006/explanation")
    assert r.status_code == 409 and len(calls) == 2
