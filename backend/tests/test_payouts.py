"""Refund safety: approvals bound to scope, duplicate lock, pause, ambiguous provider results, finality."""
import threading

import pytest

from ledgerline import db, ledger, payouts
from ledgerline.demo import run_step
from ledgerline.payouts import Paused, PayoutError, StaleApproval

from .conftest import one, q, run_to


def _pending_approval(ctx):
    return one(ctx, "SELECT * FROM approvals WHERE status = 'pending' AND deposit_id = 'DEP-1006'")


def _approve(ctx):
    a = _pending_approval(ctx)
    payouts.decide(ctx, a["id"], approve=True, actor="op", seen_scope_hash=a["scope_hash"])
    return a["id"]


def _balanced(ctx):
    with ctx.conn() as conn:
        return ledger.conservation(conn)


@pytest.fixture
def ready(ctx):
    run_to(ctx, "treasury")
    return ctx


def test_over_limit_refund_waits_for_a_person(ready):
    a = _pending_approval(ready)
    assert a is not None and a["decided_by"] is None
    assert q(ready, "SELECT * FROM operations WHERE kind='refund'") == []
    with pytest.raises(PayoutError):
        payouts.execute_refund(ready, a["id"], "op")


def test_approval_requires_the_exact_scope_seen(ready):
    a = _pending_approval(ready)
    with pytest.raises(StaleApproval):
        payouts.decide(ready, a["id"], approve=True, actor="op", seen_scope_hash="0" * 64)


def test_mutation_after_approval_invalidates_it(ready):
    aid = _approve(ready)
    # Destination changes after approval (e.g. customer updated bank details).
    with ready.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE customers SET refund_beneficiary = 'Attacker account' WHERE id = 'CUST-EASTGATE'")
    with pytest.raises(StaleApproval) as exc:
        payouts.execute_refund(ready, aid, "op")
    assert "destination" in str(exc.value)
    assert one(ready, "SELECT status FROM approvals WHERE id = ?", (aid,))["status"] == "invalidated"
    assert ready.local_bank.count_transfers() == 0


def test_new_evidence_invalidates_pending_approval(ready):
    from ledgerline.claude_reader import read_remittance  # noqa: F401

    a = _pending_approval(ready)
    # Any new evidence version on the deposit changes the bound scope.
    with ready.conn() as conn, db.transaction(conn):
        conn.execute("INSERT INTO evidence VALUES ('EV-X','DEP-1006',NULL,99,'fixture_extracted','local','{}','h','[]','advisory','x','2026-01-01T00:00:00Z')")
    with pytest.raises(StaleApproval):
        payouts.decide(ready, a["id"], approve=True, actor="op", seen_scope_hash=a["scope_hash"])


def test_concurrent_execution_sends_exactly_one_transfer(ready):
    aid = _approve(ready)
    barrier = threading.Barrier(6)
    results, errors = [], []

    def worker():
        barrier.wait()
        try:
            results.append(payouts.execute_refund(ready, aid, "op"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    assert len({r["operation"]["id"] for r in results}) == 1
    assert sum(1 for r in results if not r["replayed"]) == 1
    assert ready.local_bank.count_transfers() == 1
    assert len(q(ready, "SELECT * FROM operations WHERE kind='refund'")) == 1


def test_second_live_refund_for_same_deposit_blocked_by_lock(ready):
    aid = _approve(ready)
    payouts.execute_refund(ready, aid, "op")
    # Forge a second approved approval for the same deposit; the unique index must still refuse.
    with ready.conn() as conn, db.transaction(conn):
        a = db.row(conn, "SELECT * FROM approvals WHERE id = ?", (aid,))
        conn.execute("INSERT INTO approvals(id, operation_type, deposit_id, scope, scope_hash, status, reason, decided_by, decided_at, invalidated_reason, created_at) VALUES ('APR-FORGED','refund','DEP-1006',?,?,'approved','x','op','t',NULL,'t')",
                     (a["scope"], a["scope_hash"]))
    with pytest.raises((PayoutError, StaleApproval)):
        payouts.execute_refund(ready, "APR-FORGED", "op")
    assert ready.local_bank.count_transfers() == 1


def test_pause_blocks_execution_and_pending_retries(ready):
    aid = _approve(ready)
    with ready.conn() as conn, db.transaction(conn):
        db.set_setting(conn, "money_out_paused", True)
    with pytest.raises(Paused):
        payouts.execute_refund(ready, aid, "op")
    assert one(ready, "SELECT status FROM approvals WHERE id = ?", (aid,))["status"] == "approved"
    # Matching keeps running while paused.
    with ready.conn() as conn, db.transaction(conn):
        db.set_setting(conn, "money_out_paused", False)
    ready.local_bank.next_transfer_fault = "timeout_before_accept"
    op = payouts.execute_refund(ready, aid, "op")["operation"]
    assert op["needs_reconciliation"] == 1
    with ready.conn() as conn, db.transaction(conn):
        db.set_setting(conn, "money_out_paused", True)
    with pytest.raises(Paused):
        payouts.sync_operation(ready, op["id"])
    assert ready.local_bank.count_transfers() == 0


def test_timeout_after_accept_is_reconciled_not_resent(ready):
    aid = _approve(ready)
    ready.local_bank.next_transfer_fault = "timeout_after_accept"
    op = payouts.execute_refund(ready, aid, "op")["operation"]
    assert op["status"] == "processing" and op["needs_reconciliation"] == 1 and op["provider_id"] is None
    assert ready.local_bank.count_transfers() == 1  # the bank did record it
    op = payouts.sync_operation(ready, op["id"])  # looks up by request_id first
    assert op["needs_reconciliation"] == 0 and op["provider_id"]
    assert ready.local_bank.count_transfers() == 1
    assert _balanced(ready)["all_balanced"]


def test_timeout_before_accept_retries_once_with_same_request_id(ready):
    aid = _approve(ready)
    ready.local_bank.next_transfer_fault = "timeout_before_accept"
    op = payouts.execute_refund(ready, aid, "op")["operation"]
    assert ready.local_bank.count_transfers() == 0
    op2 = payouts.sync_operation(ready, op["id"])
    assert op2["request_id"] == op["request_id"] == payouts.request_id_for(aid)
    assert ready.local_bank.count_transfers() == 1
    assert ready.local_bank.find_transfer(op["request_id"]) is not None


def test_sent_is_not_final_and_liability_stays_until_paid(ready):
    aid = _approve(ready)
    op = payouts.execute_refund(ready, aid, "op")["operation"]
    op = payouts.simulate_bank_status(ready, op["id"], "SENT")
    gbp = _balanced(ready)["currencies"]["GBP"]
    assert op["status"] == "sent"
    assert gbp["refunds_pending"] == 480_000 and gbp["refunds_paid"] == 0 and gbp["balanced"]
    assert one(ready, "SELECT status FROM deposits WHERE id='DEP-1006'")["status"] == "refund_in_flight"
    op = payouts.simulate_bank_status(ready, op["id"], "PAID")
    gbp = _balanced(ready)["currencies"]["GBP"]
    assert gbp["refunds_pending"] == 0 and gbp["refunds_paid"] == 480_000 and gbp["balanced"]


def test_failed_after_send_returns_funds_to_unapplied(ready):
    aid = _approve(ready)
    op = payouts.execute_refund(ready, aid, "op")["operation"]
    payouts.simulate_bank_status(ready, op["id"], "SENT")
    op = payouts.simulate_bank_status(ready, op["id"], "FAILED")
    gbp = _balanced(ready)["currencies"]["GBP"]
    assert op["status"] == "failed" and gbp["unapplied"] == 480_000 and gbp["balanced"]
    assert one(ready, "SELECT status FROM deposits WHERE id='DEP-1006'")["status"] == "escalated"


def test_rejected_by_provider_releases_reservation(ready):
    aid = _approve(ready)
    ready.local_bank.next_transfer_fault = "reject"
    op = payouts.execute_refund(ready, aid, "op")["operation"]
    assert op["status"] == "failed"
    assert _balanced(ready)["currencies"]["GBP"]["unapplied"] == 480_000
    assert _balanced(ready)["all_balanced"]


def test_full_demo_scorecard(ctx):
    run_to(ctx, "treasury")
    _approve(ctx)
    for step in ("approve", "bank_sent", "bank_paid"):
        run_step(ctx, step, "op")
    from ledgerline.demo import scorecard

    s = scorecard(ctx)
    assert (s["deposits"], s["settled_without_human"], s["approvals_by_person"], s["escalations"], s["double_payments"]) == (6, 4, 1, 1, 0)
    assert s["ledger_balanced"]
