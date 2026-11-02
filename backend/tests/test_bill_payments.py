"""Paying bills through the bank: second person, funded only, one payment, SENT is not final."""
import threading
from datetime import timedelta

import pytest

from ledgerline import bill_payments as bp
from ledgerline import db, ledger, treasury, workspace
from ledgerline.payouts import Paused, PayoutError, SelfApproval, StaleApproval
from ledgerline.providers.base import ProviderAmbiguous

from .conftest import q
from .test_saas import _invite_and_join


@pytest.fixture
def empty(settings):
    from ledgerline.api.app import build_context

    return build_context(settings)


def make_bill(ctx, amount="500", cash="5000"):
    if cash:
        workspace.set_opening_balance(ctx, {"currency": "EUR", "amount": cash}, "owner")
    due = (ctx.clock.now() + timedelta(days=2)).date().isoformat()
    return workspace.create_obligation(ctx, {"payee": "Hosting", "currency": "EUR", "amount": amount, "due_date": due}, "op")["id"]


def approved(ctx, bill):
    p = bp.propose(ctx, bill, "Hosting GmbH EUR", "alice")
    return bp.decide(ctx, p["id"], approve=True, actor="bob", seen_scope_hash=p["scope_hash"])


def cash(ctx):
    with ctx.conn() as conn:
        return treasury.wallet_position(conn, ctx)["EUR"]["cash"]


def bill_status(ctx, bill):
    return q(ctx, "SELECT status FROM obligations WHERE id = ?", (bill,))[0]["status"]


def test_full_path_cash_moves_only_on_paid(empty):
    bill = make_bill(empty)
    p = approved(empty, bill)
    sent = bp.execute(empty, p["id"], "bob")
    assert sent["status"] == "processing" and sent["provider_id"] and cash(empty) == 500_000
    assert bp.simulate(empty, p["id"], "SENT", "bob")["status"] == "sent"
    assert cash(empty) == 500_000 and bill_status(empty, bill) == "scheduled"  # SENT is not final
    assert bp.simulate(empty, p["id"], "PAID", "bob")["status"] == "paid"
    assert cash(empty) == 450_000 and bill_status(empty, bill) == "paid"
    with empty.conn() as conn:
        assert ledger.conservation(conn)["all_balanced"]


def test_proposer_cannot_approve_and_unapproved_cannot_send(empty):
    p = bp.propose(empty, make_bill(empty), "Hosting GmbH EUR", "alice")
    with pytest.raises(SelfApproval):
        bp.decide(empty, p["id"], approve=True, actor="alice", seen_scope_hash=p["scope_hash"])
    with pytest.raises(PayoutError):
        bp.execute(empty, p["id"], "alice")


def test_only_a_bill_the_plan_funds_can_be_paid(empty):
    bill = make_bill(empty, amount="9000")
    with pytest.raises(PayoutError, match="not fund"):
        bp.propose(empty, bill, "Hosting GmbH EUR", "alice")


def test_funds_are_checked_again_when_sending(empty):
    bill = make_bill(empty, amount="3000")
    p = approved(empty, bill)
    with empty.conn() as conn, db.transaction(conn):
        from ledgerline.context import validate_policy

        db.set_setting(conn, "policy", validate_policy({"ring_fenced_minor": {"USD": 0, "EUR": 200_000, "GBP": 0}}))
    with pytest.raises(PayoutError, match="not fund"):
        bp.execute(empty, p["id"], "bob")
    assert bill_status(empty, bill) == "scheduled" and not q(empty, "SELECT provider_id FROM bill_payments")[0]["provider_id"]


def test_changed_bill_voids_the_approval(empty):
    bill = make_bill(empty)
    p = approved(empty, bill)
    with empty.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE obligations SET amount_minor = 60000 WHERE id = ?", (bill,))
    with pytest.raises(StaleApproval):
        bp.execute(empty, p["id"], "bob")
    assert q(empty, "SELECT status FROM bill_payments")[0]["status"] == "invalidated"


def test_stale_screen_cannot_approve(empty):
    p = bp.propose(empty, make_bill(empty), "Hosting GmbH EUR", "alice")
    with pytest.raises(StaleApproval):
        bp.decide(empty, p["id"], approve=True, actor="bob", seen_scope_hash="old")


def test_one_live_payment_per_bill_and_retry_after_failure(empty):
    bill = make_bill(empty)
    p = approved(empty, bill)
    with pytest.raises(PayoutError, match="duplicate"):
        bp.propose(empty, bill, "Someone Else", "carol")
    bp.execute(empty, p["id"], "bob")
    assert bp.simulate(empty, p["id"], "FAILED", "bob")["status"] == "failed"
    assert cash(empty) == 500_000 and bill_status(empty, bill) == "scheduled"
    assert bp.propose(empty, bill, "Someone Else", "carol")["status"] == "proposed"


def test_concurrent_sends_reach_the_bank_once(empty):
    p = approved(empty, make_bill(empty))
    calls, real = [], empty.provider.create_transfer

    def counted(**kw):
        calls.append(kw["request_id"])
        return real(**kw)

    empty.provider.create_transfer = counted
    threads = [threading.Thread(target=bp.execute, args=(empty, p["id"], "bob")) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1


def test_timeout_after_accept_is_reconciled_without_a_second_transfer(empty):
    p = approved(empty, make_bill(empty))
    empty.local_bank.next_transfer_fault = "timeout_after_accept"
    after = bp.execute(empty, p["id"], "bob")
    assert after["status"] == "processing" and after["needs_reconciliation"] == 1 and not after["provider_id"]
    with empty.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE bill_payments SET lease_until = NULL")
    fixed = bp.sync(empty, p["id"], "bob")
    assert fixed["provider_id"] and fixed["needs_reconciliation"] == 0
    with empty.local_bank._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM transfers").fetchone()[0] == 1


def test_rejection_marks_failed_and_keeps_the_bill(empty):
    bill = make_bill(empty)
    p = approved(empty, bill)
    empty.local_bank.next_transfer_fault = "reject"
    assert bp.execute(empty, p["id"], "bob")["status"] == "failed"
    assert bill_status(empty, bill) == "scheduled"


def test_pause_blocks_sending(empty):
    p = approved(empty, make_bill(empty))
    with empty.conn() as conn, db.transaction(conn):
        db.set_setting(conn, "money_out_paused", True)
    with pytest.raises(Paused):
        bp.execute(empty, p["id"], "bob")
    assert q(empty, "SELECT status FROM bill_payments")[0]["status"] == "approved"


def test_mark_paid_and_defer_refused_while_a_payment_is_live(empty):
    bill = make_bill(empty)
    approved(empty, bill)
    with pytest.raises(treasury.TreasuryError, match="in progress"):
        treasury.mark_bill_paid(empty, bill, "op")


def test_connected_account_requires_its_own_beneficiary_in_the_bill_currency(empty):
    class Sandbox:
        def list_beneficiaries(self):
            return [{"id": "ben_eur", "beneficiary": {"bank_details": {"account_currency": "EUR"}}},
                    {"id": "ben_gbp", "beneficiary": {"bank_details": {"account_currency": "GBP"}}}]

    bill = make_bill(empty)
    empty.sandbox = Sandbox()
    with pytest.raises(PayoutError, match="not on the connected"):
        bp.propose(empty, bill, "ben_unknown", "alice")
    with pytest.raises(PayoutError, match="paid in GBP"):
        bp.propose(empty, bill, "ben_gbp", "alice")
    assert bp.propose(empty, bill, "ben_eur", "alice")["destination"] == "ben_eur"


def test_api_second_member_flow_viewer_blocked_and_reset_still_works(client, app):
    client.post("/api/demo/step", json={"step": "deposits"})
    bills = client.get("/api/treasury/decisions").json()["decisions"]
    fund = next(b for b in bills if b["decision"] == "fund")
    r = client.post(f"/api/treasury/obligations/{fund['obligation_id']}/pay", json={"destination": "Payroll account"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert client.post(f"/api/treasury/bill-payments/{p['id']}/approve", json={"scope_hash": p["scope_hash"]}).status_code == 403
    viewer = _invite_and_join(client, app, "v@northbeam.test", "viewer")
    assert viewer.post(f"/api/treasury/bill-payments/{p['id']}/approve", json={"scope_hash": p["scope_hash"]}).status_code == 403
    assert any(w["id"] == p["id"] for w in client.get("/api/overview").json()["work_queue"])
    op = _invite_and_join(client, app, "o@northbeam.test", "operator")
    assert op.post(f"/api/treasury/bill-payments/{p['id']}/approve", json={"scope_hash": p["scope_hash"]}).status_code == 200
    sent = op.post(f"/api/treasury/bill-payments/{p['id']}/execute").json()
    assert sent["status"] == "processing"
    for s in ("SENT", "PAID"):
        assert op.post(f"/api/treasury/bill-payments/{p['id']}/simulate-bank", json={"next_status": s}).status_code == 200
    assert client.get("/api/treasury/bill-payments").json()[0]["status"] == "paid"
    assert client.get("/api/ledger").json()["conservation"]["all_balanced"]
    assert client.post("/api/demo/step", json={"step": "seed"}).status_code == 200  # reset clears decisions and payments
    assert client.get("/api/treasury/bill-payments").json() == []
