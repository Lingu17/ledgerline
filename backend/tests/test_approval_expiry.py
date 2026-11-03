"""An approval that is not acted on within the policy window expires and goes back to the approvers. Nothing is deleted."""
from datetime import timedelta

import pytest

from ledgerline import bill_payments, db, payouts, treasury
from ledgerline.clock import parse_iso

from .conftest import one, run_to
from .test_two_person import approved_by


def at(monkeypatch, ctx, when):
    monkeypatch.setattr(ctx.clock, "now", lambda: when)


def test_one_second_before_the_window_it_still_sends(ctx, monkeypatch):
    a = approved_by(ctx, "proposer@test")
    decided = parse_iso(one(ctx, "SELECT decided_at FROM approvals WHERE id = ?", (a["id"],))["decided_at"])
    at(monkeypatch, ctx, decided + timedelta(hours=72) - timedelta(seconds=1))
    assert payouts.execute_refund(ctx, a["id"], "approver@test")["operation"]


def test_exactly_at_the_window_it_expires_and_goes_back_to_the_approvers(ctx, monkeypatch):
    a = approved_by(ctx, "proposer@test")
    decided = parse_iso(one(ctx, "SELECT decided_at FROM approvals WHERE id = ?", (a["id"],))["decided_at"])
    at(monkeypatch, ctx, decided + timedelta(hours=72))
    with pytest.raises(payouts.StaleApproval, match="expired"):
        payouts.execute_refund(ctx, a["id"], "approver@test")
    row = one(ctx, "SELECT * FROM approvals WHERE id = ?", (a["id"],))
    assert row["status"] == "pending" and row["decided_by"] is None
    assert one(ctx, "SELECT COUNT(*) AS n FROM operations WHERE kind = 'refund'")["n"] == 0
    ev = one(ctx, "SELECT * FROM audit_events WHERE action = 'approval.expired'")
    assert ev and "approver@test" in ev["detail"]
    # A person approves again, and it can be sent.
    payouts.decide(ctx, a["id"], approve=True, actor="approver@test", seen_scope_hash=row["scope_hash"])
    assert payouts.execute_refund(ctx, a["id"], "sender@test")["operation"]


def test_the_automatic_sender_skips_an_expired_policy_approval(ctx, monkeypatch):
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
        db.set_setting(conn, "money_out_paused", False)
    at(monkeypatch, ctx, parse_iso(a["decided_at"]) + timedelta(hours=73))
    assert payouts.auto_execute_ready(ctx) == []
    assert one(ctx, "SELECT status FROM approvals WHERE id = ?", (a["id"],))["status"] == "pending"
    assert one(ctx, "SELECT COUNT(*) AS n FROM operations WHERE kind = 'refund'")["n"] == 0


def test_practice_companies_never_expire(client, app, monkeypatch):
    client.post("/api/demo/step", json={"step": "deposits"})
    client.post("/api/deposits/DEP-1006/ask-agent")
    a = next(x for x in client.get("/api/approvals").json() if x["deposit_id"] == "DEP-1006")
    client.post(f"/api/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]})
    ctx = app.state.orgs.get(client.org_id)
    with ctx.conn() as conn, db.transaction(conn):  # approved five days ago (moving the clock would end the sign-in session)
        conn.execute("UPDATE approvals SET decided_at = ? WHERE id = ?", ("2020-01-01T00:00:00Z", a["id"]))
    assert client.post(f"/api/approvals/{a['id']}/send-as-practice-teammate").status_code == 200


def test_a_bill_payment_approval_expires_too(ctx, monkeypatch):
    run_to(ctx, "deposits")
    funded = next(d for d in treasury.refresh_decisions(ctx, "t")["decisions"] if d["decision"] == "fund")
    p = bill_payments.propose(ctx, funded["obligation_id"], "Payee", "proposer@test")
    bill_payments.decide(ctx, p["id"], approve=True, actor="approver@test", seen_scope_hash=p["scope_hash"])
    decided = parse_iso(one(ctx, "SELECT decided_at FROM bill_payments WHERE id = ?", (p["id"],))["decided_at"])
    at(monkeypatch, ctx, decided + timedelta(hours=72))
    with pytest.raises(payouts.StaleApproval, match="expired"):
        bill_payments.execute(ctx, p["id"], "approver@test")
    row = one(ctx, "SELECT * FROM bill_payments WHERE id = ?", (p["id"],))
    assert row["status"] == "proposed" and row["decided_by"] is None
    assert one(ctx, "SELECT * FROM audit_events WHERE action = 'bill_payment.approval_expired'")
    bill_payments.decide(ctx, p["id"], approve=True, actor="approver@test", seen_scope_hash=row["scope_hash"])
    assert bill_payments.execute(ctx, p["id"], "approver@test")["status"] in ("processing", "sent", "paid")
