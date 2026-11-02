"""The agent asks by itself: nobody clicks, the checks still apply, and an unreachable agent loses nothing."""
from types import SimpleNamespace

import pytest

from ledgerline import agent_loop, audit, db, demo, ledger, payouts, watcher
from ledgerline.reconcile import pending_agent_questions

from .conftest import one, run_to
from .test_saas import _invite_and_join


def real_company(ctx):
    ctx.org = {"id": "org_x", "name": "X", "kind": "workspace", "bank_mode": "local"}
    return ctx


def waiting(ctx):
    with ctx.conn() as conn:
        return pending_agent_questions(conn)


def test_real_company_gets_the_reference_result_with_no_click(ctx):
    run_to(ctx, "links")
    assert len(waiting(ctx)) == 3
    agent_loop.on_arrival(real_company(ctx))
    assert waiting(ctx) == []
    s = demo.scorecard(ctx)
    assert (s["deposits"], s["settled_without_human"], s["approvals_by_person"], s["escalations"], s["double_payments"]) == (6, 4, 1, 1, 0)
    assert one(ctx, "SELECT status FROM deposits WHERE id = 'DEP-1005'")["status"] == "credited"
    assert one(ctx, "SELECT status FROM deposits WHERE id = 'DEP-1004'")["status"] == "escalated"
    assert one(ctx, "SELECT status FROM deposits WHERE id = 'DEP-1006'")["status"] == "refund_awaiting_approval"
    assert one(ctx, "SELECT COUNT(*) AS n FROM operations WHERE kind = 'refund'")["n"] == 0  # over the limit: still a person's call
    with ctx.conn() as conn:
        assert ledger.conservation(conn)["all_balanced"]


def test_practice_company_stays_paused_to_be_watched(ctx):
    run_to(ctx, "links")
    ctx.org = {"id": "org_x", "name": "X", "kind": "sample", "bank_mode": "local"}
    agent_loop.on_arrival(ctx)
    assert len(waiting(ctx)) == 3


def test_asking_twice_books_each_answer_once(ctx):
    run_to(ctx, "links")
    agent_loop.ask_pending(ctx)
    assert agent_loop.ask_pending(ctx)["asked"] == 0
    assert one(ctx, "SELECT COUNT(*) AS n FROM evidence WHERE deposit_id = 'DEP-1005'")["n"] == 1


def test_unreachable_agent_leaves_the_payment_waiting(ctx, monkeypatch):
    run_to(ctx, "links")

    def down(*_a, **_k):
        raise OSError("test-only")
    monkeypatch.setattr(agent_loop, "explain_payments", down)
    assert agent_loop.ask_pending(ctx)["error"] == "OSError"
    assert len(waiting(ctx)) == 3


def test_watcher_retries_waiting_payments_on_connected_accounts(ctx):
    run_to(ctx, "links")
    control = SimpleNamespace(all_org_ids=lambda: ["org_a"], org=lambda _id: {"bank_mode": "airwallex_sandbox", "created_at": "2020-01-01T00:00:00Z"})
    assert watcher.sweep(SimpleNamespace(get=lambda _id: ctx), control) == 1
    assert waiting(ctx) == []


def test_new_practice_payment_is_handled_with_no_further_click(client):
    client.post("/api/demo/step", json={"step": "deposits"})
    r = client.post("/api/demo/practice-unclear-payment")
    assert r.status_code == 200, r.text
    detail = client.get(f"/api/deposits/{r.json()['deposit_id']}").json()
    assert detail["status"] == "credited" and detail["evidence"][0]["verdict"] == "verified"
    assert [p["kind"] for p in detail["plans"]][0] == "initial" and len(detail["plans"]) == 2
    assert client.post("/api/demo/practice-unclear-payment").json()["created"] is False
    assert client.get("/api/ledger").json()["conservation"]["all_balanced"]


def test_viewer_cannot_trigger_a_practice_payment(client, app):
    viewer = _invite_and_join(client, app, "v8@northbeam.test", "viewer")
    assert viewer.post("/api/demo/practice-unclear-payment").status_code == 403


def new_unclear_payment(ctx, ref):
    from ledgerline.reconcile import ingest_deposit

    with ctx.conn() as conn, db.transaction(conn):
        return ingest_deposit(conn, ctx, {"provider_ref": ref, "currency": "USD", "amount_minor": 120_000, "payer_name": "DUNMORE ANALYTICS LLC",
                                          "reference": "", "received_at": "2026-11-01T00:00:00Z"}, source="manual_import")[0]


def set_refund_limit(ctx, ccy, minor):
    with ctx.conn() as conn, db.transaction(conn):
        policy = dict(ctx.policy(conn))
        policy["refund_auto_limit_minor"] = {**policy["refund_auto_limit_minor"], ccy: minor}
        db.set_setting(conn, "policy", policy)


def refunds(ctx):
    return one(ctx, "SELECT COUNT(*) AS n FROM operations WHERE kind = 'refund'")["n"]


def test_refund_a_person_approved_but_held_back_stays_held_when_another_payment_arrives(ctx):
    run_to(ctx, "agents")
    a = one(ctx, "SELECT * FROM approvals WHERE deposit_id = 'DEP-1006'")
    payouts.decide(ctx, a["id"], approve=True, actor="approver@test", seen_scope_hash=a["scope_hash"])
    new_unclear_payment(ctx, "NEW-1")
    assert agent_loop.ask_pending(ctx)["asked"] == 1
    assert refunds(ctx) == 0  # a person must press send; nothing sends it automatically
    assert one(ctx, "SELECT status FROM approvals WHERE id = ?", (a["id"],))["status"] == "approved"


def test_refund_under_the_limit_with_verified_evidence_goes_with_no_person(ctx):
    run_to(ctx, "links")
    set_refund_limit(ctx, "GBP", 500_000)
    agent_loop.on_arrival(real_company(ctx))
    assert one(ctx, "SELECT decided_by FROM approvals WHERE deposit_id = 'DEP-1006'")["decided_by"] == "policy:auto_limit"
    assert refunds(ctx) == 1


def test_pause_stops_the_agent_sending_a_refund(ctx):
    run_to(ctx, "links")
    set_refund_limit(ctx, "GBP", 500_000)
    with ctx.conn() as conn, db.transaction(conn):
        db.set_setting(conn, "money_out_paused", True)
    agent_loop.on_arrival(real_company(ctx))
    assert refunds(ctx) == 0
    assert one(ctx, "SELECT status FROM deposits WHERE id = 'DEP-1005'")["status"] == "credited"  # matching keeps running


def test_real_webhook_on_a_real_company_reaches_the_agent_with_no_click(client, app):
    from .test_api_webhooks import _event, _post

    client.post("/api/demo/step", json={"step": "seed"})
    app.state.orgs.get(client.org_id).org["kind"] = "workspace"
    r = _post(client, _event(eid="evt_auto", ref="AWX-AUTO-1", amount=1200.00, payer="DUNMORE ANALYTICS LLC", reference=""))
    assert r.status_code == 200, r.text
    d = client.get(f"/api/deposits/{r.json()['deposit_id']}").json()
    assert d["status"] == "credited" and d["evidence"][0]["verdict"] == "verified"


def set_paused(ctx, paused):
    with ctx.conn() as conn, db.transaction(conn):
        db.set_setting(conn, "money_out_paused", paused)


def policy_approved_refund_held_by_pause(ctx):
    run_to(ctx, "links")
    set_refund_limit(ctx, "GBP", 500_000)
    set_paused(ctx, True)
    agent_loop.on_arrival(real_company(ctx))
    a = one(ctx, "SELECT * FROM approvals WHERE deposit_id = 'DEP-1006'")
    assert a["decided_by"] == "policy:auto_limit" and refunds(ctx) == 0
    return a


def test_limit_lowered_while_paused_moves_the_refund_to_a_second_person(ctx):
    a = policy_approved_refund_held_by_pause(ctx)
    set_refund_limit(ctx, "GBP", 100_000)
    set_paused(ctx, False)
    assert payouts.auto_execute_ready(ctx) == []
    assert refunds(ctx) == 0
    now = one(ctx, "SELECT * FROM approvals WHERE id = ?", (a["id"],))
    assert (now["status"], now["decided_by"], now["decided_at"]) == ("pending", None, None)
    event = one(ctx, "SELECT * FROM audit_events WHERE action = 'approval.returned_to_person' AND entity_id = ?", (a["id"],))
    assert "limit" in event["detail"]
    with ctx.conn() as conn:
        assert audit.verify_chain(conn)["ok"]
    # The normal path takes over: a second person approves, a person sends, under the same scope.
    payouts.decide(ctx, a["id"], approve=True, actor="approver@test", seen_scope_hash=a["scope_hash"])
    payouts.execute_refund(ctx, a["id"], "operator@test")
    assert refunds(ctx) == 1


def test_refund_still_under_the_limit_sends_automatically_after_resume(ctx):
    a = policy_approved_refund_held_by_pause(ctx)
    set_refund_limit(ctx, "GBP", 480_000)  # exactly the refund: still within the limit
    set_paused(ctx, False)
    assert payouts.auto_execute_ready(ctx) == [a["id"]]
    assert refunds(ctx) == 1


def test_nothing_changes_or_sends_while_the_pause_is_active(ctx):
    a = policy_approved_refund_held_by_pause(ctx)
    set_refund_limit(ctx, "GBP", 100_000)
    assert payouts.auto_execute_ready(ctx) == []
    assert refunds(ctx) == 0
    assert one(ctx, "SELECT status FROM approvals WHERE id = ?", (a["id"],))["status"] == "approved"


def test_person_approved_refund_over_the_new_limit_can_still_be_sent(ctx):
    run_to(ctx, "agents")
    a = one(ctx, "SELECT * FROM approvals WHERE deposit_id = 'DEP-1006'")
    payouts.decide(ctx, a["id"], approve=True, actor="approver@test", seen_scope_hash=a["scope_hash"])
    set_refund_limit(ctx, "GBP", 100)
    assert payouts.auto_execute_ready(ctx) == []  # never sent automatically
    assert one(ctx, "SELECT status FROM approvals WHERE id = ?", (a["id"],))["status"] == "approved"  # and not sent back
    payouts.execute_refund(ctx, a["id"], "operator@test")
    assert refunds(ctx) == 1


def test_pressing_execute_over_a_lowered_limit_returns_it_to_a_second_person(ctx):
    a = policy_approved_refund_held_by_pause(ctx)
    set_refund_limit(ctx, "GBP", 100_000)
    set_paused(ctx, False)
    with pytest.raises(payouts.StaleApproval, match="second person"):
        payouts.execute_refund(ctx, a["id"], "operator@test")
    assert refunds(ctx) == 0
    now = one(ctx, "SELECT * FROM approvals WHERE id = ?", (a["id"],))
    assert (now["status"], now["decided_by"], now["decided_at"]) == ("pending", None, None)
    assert one(ctx, "SELECT COUNT(*) AS n FROM audit_events WHERE action = 'approval.returned_to_person' AND entity_id = ?", (a["id"],))["n"] == 1
    payouts.decide(ctx, a["id"], approve=True, actor="approver@test", seen_scope_hash=a["scope_hash"])
    payouts.execute_refund(ctx, a["id"], "operator@test")
    assert refunds(ctx) == 1


def test_pressing_execute_under_the_limit_still_sends(ctx):
    a = policy_approved_refund_held_by_pause(ctx)
    set_paused(ctx, False)
    assert payouts.execute_refund(ctx, a["id"], "operator@test")["operation"]["status"]
    assert refunds(ctx) == 1
