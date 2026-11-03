"""Over-limit money-out always involves two people. When the proposer is the agent, the approver cannot also send it."""
import pytest

from ledgerline import db, payouts, treasury
from ledgerline import bill_payments

from ledgerline.demo import run_step

from .conftest import new_client, one, run_to, signup
from .test_saas import _invite_and_join


def setup_refund(client):
    client.post("/api/demo/step", json={"step": "deposits"})
    assert client.post("/api/deposits/DEP-1006/ask-agent").status_code == 200
    a = next(x for x in client.get("/api/approvals").json() if x["deposit_id"] == "DEP-1006")
    assert a["status"] == "pending" and a["created_by"] == "system"
    return a


def refund_ops(client):
    return [o for o in client.get("/api/operations").json() if o["kind"] == "refund"]


def transfers(client, app):
    return app.state.orgs.get(client.org_id).local_bank.count_transfers("Ledgerline refund DEP-1006")


def test_one_operator_cannot_approve_and_send_an_agent_proposed_refund(client, app):
    a = setup_refund(client)
    assert client.post(f"/api/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]}).status_code == 200
    r = client.post(f"/api/approvals/{a['id']}/execute")
    assert r.status_code == 403 and "different team member" in r.json()["detail"]
    assert refund_ops(client) == [] and transfers(client, app) == 0
    assert next(x for x in client.get("/api/approvals").json() if x["id"] == a["id"])["status"] == "approved"


def test_a_different_operator_can_send_it(client, app):
    a = setup_refund(client)
    client.post(f"/api/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]})
    other = _invite_and_join(client, app, "sender@northbeam.test", "operator")
    assert other.post(f"/api/approvals/{a['id']}/execute").status_code == 200
    assert len(refund_ops(client)) == 1 and transfers(client, app) == 1


def test_the_approvals_list_says_when_the_sender_must_differ(client):
    a = setup_refund(client)
    assert a["sender_must_differ"] is True


def approved_by(ctx, created_by, decided_by="approver@test"):
    run_to(ctx, "agents")
    a = one(ctx, "SELECT * FROM approvals WHERE deposit_id = 'DEP-1006'")
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE approvals SET created_by = ? WHERE id = ?", (created_by, a["id"]))
    payouts.decide(ctx, a["id"], approve=True, actor=decided_by, seen_scope_hash=a["scope_hash"])
    return a


@pytest.mark.parametrize("created_by", [None, "", "system", "rules", "agent:auto", "policy:auto_limit"])
def test_anything_that_is_not_a_person_counts_as_not_a_person(ctx, created_by):
    a = approved_by(ctx, created_by)
    with pytest.raises(payouts.SelfApproval):
        payouts.execute_refund(ctx, a["id"], "approver@test")
    assert payouts.execute_refund(ctx, a["id"], "someone.else@test")["operation"]


@pytest.mark.parametrize("sender", ["proposer@test", "approver@test"])
def test_person_proposed_refund_can_be_sent_by_either_person(ctx, sender):
    a = approved_by(ctx, "proposer@test")
    assert payouts.execute_refund(ctx, a["id"], sender)["operation"]


def test_refund_returned_after_the_limit_was_lowered_follows_the_same_rule(ctx):
    run_to(ctx, "links")
    with ctx.conn() as conn, db.transaction(conn):
        p = dict(ctx.policy(conn))
        p["refund_auto_limit_minor"] = {**p["refund_auto_limit_minor"], "GBP": 500_000}
        db.set_setting(conn, "policy", p)
        db.set_setting(conn, "money_out_paused", True)
    from ledgerline import agent_loop

    agent_loop.ask_pending(ctx)
    a = one(ctx, "SELECT * FROM approvals WHERE deposit_id = 'DEP-1006'")
    assert a["decided_by"] == "policy:auto_limit"
    with ctx.conn() as conn, db.transaction(conn):
        p = dict(ctx.policy(conn))
        p["refund_auto_limit_minor"] = {**p["refund_auto_limit_minor"], "GBP": 100_000}
        db.set_setting(conn, "policy", p)
        db.set_setting(conn, "money_out_paused", False)
    payouts.auto_execute_ready(ctx)
    payouts.decide(ctx, a["id"], approve=True, actor="approver@test", seen_scope_hash=a["scope_hash"])
    with pytest.raises(payouts.SelfApproval):
        payouts.execute_refund(ctx, a["id"], "approver@test")
    assert payouts.execute_refund(ctx, a["id"], "sender@test")["operation"]


def test_policy_approved_refund_still_sends_itself(ctx):
    run_to(ctx, "links")
    with ctx.conn() as conn, db.transaction(conn):
        p = dict(ctx.policy(conn))
        p["refund_auto_limit_minor"] = {**p["refund_auto_limit_minor"], "GBP": 500_000}
        db.set_setting(conn, "policy", p)
    from ledgerline import agent_loop

    agent_loop.ask_pending(ctx)
    assert one(ctx, "SELECT COUNT(*) AS n FROM operations WHERE kind = 'refund'")["n"] == 1


def audit_events(client):
    return client.get("/api/audit/export").json()["audit_events"]


def practice_send(client, approval_id, **kw):
    return client.post(f"/api/approvals/{approval_id}/send-as-practice-teammate", **kw)


def test_practice_teammate_sends_what_the_judge_approved_and_the_walkthrough_finishes(client, app):
    a = setup_refund(client)
    for step in ("links", "agents", "treasury"):
        assert client.post("/api/demo/step", json={"step": step}).status_code == 200
    client.post(f"/api/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]})
    assert client.get("/api/demo").json()["practice_teammate_can_send"] == a["id"]
    r = practice_send(client, a["id"])
    assert r.status_code == 200, r.text
    assert len(refund_ops(client)) == 1 and transfers(client, app) == 1
    created = next(e for e in audit_events(client) if e["action"] == "refund.created")
    assert created["actor"] == "practice-teammate"
    sent = next(e for e in audit_events(client) if e["action"] == "practice_teammate.sent")
    assert sent["actor"] == "practice-teammate" and sent["detail"]["button_pressed_by"] == "owner@northbeam.test"
    assert not any(e["actor"] == "owner@northbeam.test" and e["action"].startswith("refund.") for e in audit_events(client))
    for step in ("approve", "bank_sent", "bank_paid"):
        assert client.post("/api/demo/step", json={"step": step}).status_code == 200, step
    assert all(s["done"] for s in client.get("/api/demo").json()["steps"] if s["id"] != "seed")
    assert practice_send(client, a["id"]).json()["replayed"] is True and transfers(client, app) == 1


def test_practice_teammate_is_refused_in_a_real_company_whatever_the_request_says(app):
    c = new_client(app)
    signup(c, email="fin@real.test", org="Real Co", start_with="empty")
    ctx = app.state.orgs.get(c.org_id)
    assert ctx.org["kind"] == "workspace"
    run_step(ctx, "seed", "tester")
    run_to(ctx, "agents")
    a = next(x for x in c.get("/api/approvals").json() if x["deposit_id"] == "DEP-1006")
    assert a["status"] == "pending" and a["created_by"] == "system"
    assert c.post(f"/api/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]}).status_code == 200
    for kw in ({}, {"json": {"practice": True, "kind": "sample", "actor": "practice-teammate"}},
               {"headers": {"X-Practice-Company": "1", "X-Org-Kind": "sample"}}):
        r = practice_send(c, a["id"], **kw)
        assert r.status_code == 403 and "second real member" in r.json()["detail"], r.text
    assert ctx.local_bank.count_transfers("Ledgerline refund DEP-1006") == 0
    assert [o for o in c.get("/api/operations").json() if o["kind"] == "refund"] == []
    assert next(x for x in c.get("/api/approvals").json() if x["id"] == a["id"])["status"] == "approved"
    assert not any(e["actor"] == "practice-teammate" for e in audit_events(c))
    assert "practice_teammate_can_send" not in c.get("/api/demo").json()


def test_practice_teammate_cannot_send_a_refund_it_approved(client, app):
    a = setup_refund(client)
    ctx = app.state.orgs.get(client.org_id)
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE approvals SET status='approved', decided_by='practice-teammate' WHERE id = ?", (a["id"],))
    r = practice_send(client, a["id"])
    assert r.status_code == 403 and "it approved" in r.json()["detail"]
    assert refund_ops(client) == [] and transfers(client, app) == 0


def test_practice_teammate_cannot_skip_the_approval(client, app):
    a = setup_refund(client)
    r = practice_send(client, a["id"])
    assert r.status_code == 409 and "must be approved" in r.json()["detail"]
    assert refund_ops(client) == [] and transfers(client, app) == 0


def test_bill_payment_proposer_check_ignores_letter_case(ctx):
    run_to(ctx, "deposits")
    funded = next(d for d in treasury.refresh_decisions(ctx, "t")["decisions"] if d["decision"] == "fund")
    p = bill_payments.propose(ctx, funded["obligation_id"], "Payee", "Proposer@Test")
    with pytest.raises(payouts.SelfApproval):
        bill_payments.decide(ctx, p["id"], approve=True, actor="proposer@test", seen_scope_hash=p["scope_hash"])


def test_refund_proposer_check_ignores_letter_case(ctx):
    run_to(ctx, "agents")
    a = one(ctx, "SELECT * FROM approvals WHERE deposit_id = 'DEP-1006'")
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE approvals SET created_by = ? WHERE id = ?", ("Proposer@Test", a["id"]))
    with pytest.raises(payouts.SelfApproval):
        payouts.decide(ctx, a["id"], approve=True, actor="proposer@test", seen_scope_hash=a["scope_hash"])


def test_a_bill_payment_is_never_proposed_and_approved_by_one_person(ctx):
    """Documents the finding: bill payments have a person as proposer, so the approver may send, as with person-proposed refunds."""
    run_to(ctx, "deposits")
    funded = next(d for d in treasury.refresh_decisions(ctx, "t")["decisions"] if d["decision"] == "fund")
    p = bill_payments.propose(ctx, funded["obligation_id"], "Payee", "proposer@test")
    with pytest.raises(payouts.SelfApproval):
        bill_payments.decide(ctx, p["id"], approve=True, actor="proposer@test", seen_scope_hash=p["scope_hash"])
    bill_payments.decide(ctx, p["id"], approve=True, actor="approver@test", seen_scope_hash=p["scope_hash"])
    assert bill_payments.execute(ctx, p["id"], "approver@test")["status"] in ("processing", "sent", "paid")
