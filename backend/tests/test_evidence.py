"""The three checks against tampering, replay, expiry and cross-customer claims."""
import copy
from datetime import timedelta

import pytest

from ledgerline import crypto, db
from ledgerline.clock import iso
from ledgerline.demo import run_step
from ledgerline.payer_agents.keys import ensure_keys, key_location
from ledgerline.reconcile import ReconcileError, invoice_views, key_registry, record_agent_answer
from ledgerline.evidence import verify

from .conftest import one


def _claim(ctx, deposit_id, customer_id, invoice_id, reason, amount=None, ccy=None, ttl=600):
    d = one(ctx, "SELECT * FROM deposits WHERE id = ?", (deposit_id,))
    now = ctx.clock.now()
    return {
        "schema": "ledgerline.explain_payment.v1",
        "deposit_id": deposit_id,
        "customer_id": customer_id,
        "currency": ccy or d["currency"],
        "amount_minor": d["amount_minor"] if amount is None else amount,
        "invoice_id": invoice_id,
        "reason": reason,
        "note": "test",
        "issued_at": iso(now),
        "expires_at": iso(now + timedelta(seconds=ttl)),
        "nonce": "n1",
    }


@pytest.fixture
def awaiting(ctx):
    run_step(ctx, "deposits", "t")
    run_step(ctx, "links", "t")
    return ctx


def _verify(ctx, deposit_id, asked, envelope):
    with ctx.conn() as conn:
        d = db.row(conn, "SELECT * FROM deposits WHERE id = ?", (deposit_id,))
        return verify(envelope, deposit=d, asked_customer_id=asked, registry=key_registry(conn), invoices=invoice_views(conn),
                      now=ctx.clock.now(), max_ttl_seconds=900, skew_seconds=60)


def _sign(ctx, customer_id, claim):
    return crypto.sign_claim(claim, ensure_keys(key_location(ctx.settings))[customer_id])


def _by_name(v):
    return {c["name"]: c["passed"] for c in v.checks}


def test_valid_advance_claim_passes_all_three(awaiting):
    env = _sign(awaiting, "CUST-DUNMORE", _claim(awaiting, "DEP-1005", "CUST-DUNMORE", "INV-2291", "advance_payment"))
    v = _verify(awaiting, "DEP-1005", "CUST-DUNMORE", env)
    assert v.verdict == "verified" and all(_by_name(v).values())


def test_tampered_claim_fails_signature(awaiting):
    env = _sign(awaiting, "CUST-DUNMORE", _claim(awaiting, "DEP-1005", "CUST-DUNMORE", "INV-2291", "advance_payment"))
    env["claim"]["invoice_id"] = "INV-2244"
    v = _verify(awaiting, "DEP-1005", "CUST-DUNMORE", env)
    assert v.verdict == "rejected" and _by_name(v)["signature"] is False


def test_changed_amount_fails_even_when_validly_signed(awaiting):
    env = _sign(awaiting, "CUST-DUNMORE", _claim(awaiting, "DEP-1005", "CUST-DUNMORE", "INV-2291", "advance_payment", amount=119_999))
    v = _verify(awaiting, "DEP-1005", "CUST-DUNMORE", env)
    assert _by_name(v)["signature"] is True and _by_name(v)["binding"] is False
    assert v.verdict == "rejected"


def test_expired_claim_rejected(awaiting):
    env = _sign(awaiting, "CUST-DUNMORE", _claim(awaiting, "DEP-1005", "CUST-DUNMORE", "INV-2291", "advance_payment", ttl=300))
    awaiting.clock.advance(timedelta(seconds=301))
    v = _verify(awaiting, "DEP-1005", "CUST-DUNMORE", env)
    assert v.verdict == "rejected" and "expired" in v.reason


def test_claim_for_a_different_deposit_cannot_be_replayed(awaiting):
    env = _sign(awaiting, "CUST-EASTGATE", _claim(awaiting, "DEP-1006", "CUST-EASTGATE", "INV-2238", "duplicate_payment"))
    # Present Eastgate's answer for DEP-1006 as if it explained DEP-1003 (also GBP).
    v = _verify(awaiting, "DEP-1003", "CUST-EASTGATE", env)
    assert v.verdict == "rejected" and _by_name(v)["binding"] is False


def test_foreign_invoice_claim_fails_records_check(awaiting):
    env = _sign(awaiting, "CUST-FJORD", _claim(awaiting, "DEP-1004", "CUST-FJORD", "INV-2253", "invoice_payment"))
    v = _verify(awaiting, "DEP-1004", "CUST-FJORD", env)
    assert _by_name(v) == {"signature": True, "binding": True, "records": False}
    assert "belongs to another customer" in v.reason


def test_one_customer_cannot_answer_for_another(awaiting):
    # Fjord signs a claim that pretends to be Dunmore's answer.
    claim = _claim(awaiting, "DEP-1005", "CUST-DUNMORE", "INV-2291", "advance_payment")
    env = _sign(awaiting, "CUST-FJORD", claim)
    v = _verify(awaiting, "DEP-1005", "CUST-DUNMORE", env)
    assert _by_name(v)["signature"] is False


def test_extra_fields_and_floats_rejected(awaiting):
    claim = _claim(awaiting, "DEP-1005", "CUST-DUNMORE", "INV-2291", "advance_payment")
    env = _sign(awaiting, "CUST-DUNMORE", claim)
    bad = copy.deepcopy(env)
    bad["claim"]["refund_to"] = "attacker"
    assert _verify(awaiting, "DEP-1005", "CUST-DUNMORE", bad).verdict == "rejected"
    with pytest.raises(ValueError):
        crypto.canonical_json({"amount": 1.5})


def test_duplicate_claim_against_open_invoice_rejected(awaiting):
    env = _sign(awaiting, "CUST-BRIGHTWAVE", _claim(awaiting, "DEP-1004", "CUST-BRIGHTWAVE", "INV-2253", "duplicate_payment"))
    v = _verify(awaiting, "DEP-1004", "CUST-BRIGHTWAVE", env)
    assert v.verdict == "rejected"


def test_rejected_evidence_escalates_and_moves_no_money(awaiting):
    env = _sign(awaiting, "CUST-FJORD", _claim(awaiting, "DEP-1004", "CUST-FJORD", "INV-2253", "invoice_payment"))
    with awaiting.conn() as conn, db.transaction(conn):
        r = record_agent_answer(conn, awaiting, "DEP-1004", "CUST-FJORD", {"status": "answered", "envelope": env}, "test")
    assert r["plan"]["status"] == "escalated"
    assert one(awaiting, "SELECT COUNT(*) AS n FROM allocations WHERE deposit_id='DEP-1004'")["n"] == 0
    with awaiting.conn() as conn:
        assert invoice_views(conn)["INV-2253"].remaining_minor == 175_000


def test_replayed_signed_answer_is_not_accepted_twice(awaiting):
    env = _sign(awaiting, "CUST-DUNMORE", _claim(awaiting, "DEP-1005", "CUST-DUNMORE", "INV-2291", "advance_payment"))
    with awaiting.conn() as conn, db.transaction(conn):
        record_agent_answer(conn, awaiting, "DEP-1005", "CUST-DUNMORE", {"status": "answered", "envelope": env}, "test")
    with pytest.raises(ReconcileError):
        with awaiting.conn() as conn, db.transaction(conn):
            record_agent_answer(conn, awaiting, "DEP-1005", "CUST-DUNMORE", {"status": "answered", "envelope": env}, "test")
