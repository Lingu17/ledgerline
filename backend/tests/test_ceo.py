"""The CEO view reads the same records as the detailed pages, moves nothing, and never hides a problem."""
from ledgerline import db

from .test_saas import _invite_and_join


def test_practice_company_summary_matches_the_scorecard(client):
    client.post("/api/demo/step", json={"step": "deposits"})
    c = client.get("/api/ceo").json()
    score = client.get("/api/scorecard").json()
    assert c["agent"]["payments"] == score["deposits"] == 6
    assert c["agent"]["settled_without_person"] == score["settled_without_human"]
    assert c["agent"]["estimated_minutes_saved"] == score["settled_without_human"] * c["agent"]["minutes_per_payment_assumed"]
    assert c["trust"]["ledger_balanced"] and c["trust"]["log_intact"] and c["trust"]["double_payments"] == 0
    assert {x["currency"] for x in c["currencies"]} == {"USD", "EUR", "GBP"}
    assert c["verdict"] == "attention" and c["needs_you_total"] > 0


def test_reading_it_changes_nothing_and_viewers_can_read(client, app):
    viewer = _invite_and_join(client, app, "v7@northbeam.test", "viewer")
    before = client.get("/api/audit/verify").json()["events"]
    assert viewer.get("/api/ceo").status_code == 200
    assert client.get("/api/audit/verify").json()["events"] == before


def test_tampered_log_turns_the_verdict_to_a_problem(client, app):
    client.post("/api/demo/step", json={"step": "deposits"})
    org = client.get("/api/status").json()["org"]["id"]
    with app.state.orgs.get(org).conn() as conn, db.transaction(conn):
        conn.execute("UPDATE audit_events SET actor = 'someone else' WHERE id = 1")
    c = client.get("/api/ceo").json()
    assert c["verdict"] == "problem" and not c["trust"]["log_intact"]


def test_practice_wrong_currency_is_added_once(client):
    client.post("/api/demo/step", json={"step": "deposits"})
    first = client.post("/api/demo/practice-wrong-currency")
    assert first.status_code == 200, first.text
    assert first.json()["created"] and client.post("/api/demo/practice-wrong-currency").json()["created"] is False
    options = client.get(f"/api/deposits/{first.json()['deposit_id']}/wrong-currency").json()
    assert options["applies"] and options["invoices"][0]["invoice_id"] == "INV-2253"
