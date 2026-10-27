"""Ordinary operator input keeps the same safeguards as the webhook path."""
from .conftest import OP


def _seeded(client, *steps):
    for s in ("seed",) + steps:
        assert client.post("/api/demo/step", json={"step": s}, headers=OP).status_code == 200


def test_create_customer_and_invoice_then_pay_it_manually(client):
    _seeded(client)
    c = client.post("/api/customers", json={"name": "Harbour Lane Studio", "country": "GB", "payer_names": ["HARBOUR LANE STUDIO LTD"],
                                             "refund_beneficiary": "Harbour Lane - UK account (synthetic)"}, headers=OP)
    assert c.status_code == 200, c.text
    cid = c.json()["id"]
    inv = client.post("/api/invoices", json={"customer_id": cid, "currency": "GBP", "amount": "1250.00",
                                              "due_date": "2026-12-01", "description": "Design sprint"}, headers=OP).json()
    assert inv["amount_minor"] == 125_000 and inv["status"] == "open"
    body = {"external_ref": "BANKSTMT-0001", "currency": "GBP", "amount": "1250.00", "payer_name": "Harbour Lane Studio Ltd",
            "reference": f"Paying {inv['id']}"}
    r = client.post("/api/payments", json=body, headers=OP).json()
    assert r["created"] is True
    d = client.get(f"/api/deposits/{r['deposit_id']}").json()
    assert d["source"] == "manual_import" and d["category"] == "clean_match" and d["buckets"]["allocated"] == 125_000
    # Idempotent on the external reference; different details are refused.
    assert client.post("/api/payments", json=body, headers=OP).json() == {"deposit_id": r["deposit_id"], "created": False}
    assert client.post("/api/payments", json={**body, "amount": "1251.00"}, headers=OP).status_code == 409
    assert client.get("/api/ledger").json()["conservation"]["all_balanced"]
    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert {"customer.created", "invoice.created", "payment.recorded_manually"} <= set(actions)


def test_validation_errors_are_422_with_reasons(client):
    _seeded(client)
    r = client.post("/api/customers", json={"name": "X", "country": "gb", "payer_names": [], "refund_beneficiary": ""}, headers=OP)
    assert r.status_code == 422 and r.json()["detail"]
    r = client.post("/api/customers", json={"name": "Copycat", "country": "US", "payer_names": ["ACME ROBOTICS INC"],
                                             "refund_beneficiary": "x account"}, headers=OP)
    assert r.status_code == 422 and "already identifies" in r.json()["detail"]
    r = client.post("/api/invoices", json={"customer_id": "CUST-NOPE", "currency": "USD", "amount": "10.00",
                                            "due_date": "2026-12-01", "description": "x"}, headers=OP)
    assert r.status_code == 422
    r = client.post("/api/payments", json={"external_ref": "bad ref!", "currency": "USD", "amount": "10.00",
                                            "payer_name": "ACME ROBOTICS INC"}, headers=OP)
    assert r.status_code == 422
    r = client.post("/api/payments", json={"external_ref": "future", "currency": "USD", "amount": "10.00",
                                            "payer_name": "ACME ROBOTICS INC", "received_at": "2099-01-01"}, headers=OP)
    assert r.status_code == 422


def test_operator_cannot_allocate_escalated_payment_to_another_customers_invoice(client):
    _seeded(client, "deposits", "links", "agents")
    r = client.post("/api/deposits/DEP-1004/resolve", json={"action": "allocate", "invoice_id": "INV-2253", "amount": "1750.00",
                                                             "note": "Fjord says it pays for Brightwave"}, headers=OP)
    assert r.status_code == 422 and "belongs to CUST-BRIGHTWAVE" in r.json()["detail"]
    r = client.post("/api/deposits/DEP-1004/resolve", json={"action": "allocate", "invoice_id": "INV-2253", "amount": "1750.00",
                                                             "customer_id": "CUST-BRIGHTWAVE", "note": "x y z"}, headers=OP)
    assert r.status_code == 422 and "cannot be applied to another customer" in r.json()["detail"]


def test_operator_partial_credit_then_rest_resolves(client):
    _seeded(client, "deposits", "links", "agents")
    r = client.post("/api/deposits/DEP-1004/resolve", json={"action": "credit", "amount": "1000.00", "note": "Fjord asked to hold as credit"}, headers=OP)
    assert r.status_code == 200, r.text
    d = client.get("/api/deposits/DEP-1004").json()
    assert d["status"] == "escalated" and d["buckets"]["credited"] == 100_000 and d["buckets"]["unapplied"] == 75_000
    assert client.post("/api/deposits/DEP-1004/resolve", json={"action": "credit", "amount": "750.01", "note": "too much"},
                       headers=OP).status_code == 422
    assert client.get("/api/ledger").json()["conservation"]["all_balanced"]


def test_paused_operator_resolution_still_works_because_no_money_leaves(client):
    _seeded(client, "deposits", "links", "agents")
    client.post("/api/settings/pause", json={"paused": True}, headers=OP)
    r = client.post("/api/deposits/DEP-1004/resolve", json={"action": "credit", "amount": "1750.00", "note": "hold"}, headers=OP)
    assert r.status_code == 200 and client.get("/api/deposits/DEP-1004").json()["status"] == "credited"


def test_free_text_remittance_is_read_and_stays_advisory(client):
    _seeded(client, "deposits")
    text = "Hello team, this transfer covers inv 2240 for implementation services. Regards, Acme AP"
    r = client.post("/api/deposits/DEP-1003/read-remittance", json={"text": text}, headers=OP).json()
    assert r["source"] == "fixture_extracted" and r["proposal"]["input"]["invoice_id"] == "INV-2240"
    assert any(c["name"] == "records" and not c["passed"] for c in r["checks"])  # INV-2240 is Acme's, payer is Calder
    assert client.post("/api/deposits/DEP-1003/read-remittance", json={"text": "short"}, headers=OP).status_code == 409


def test_manual_payment_unavailable_in_sandbox_mode(settings):
    from ledgerline.context import AppContext
    from ledgerline.workspace import InputError, record_manual_payment
    import pytest

    ctx = AppContext(settings=settings, clock=None, provider=None, local_bank=None)
    with pytest.raises(InputError, match="local workspace"):
        record_manual_payment(ctx, {}, "op")


def test_statement_dated_today_is_accepted_at_any_hour(client):
    """Regression (found by the browser E2E suite): the form's default date is today, which was
    pinned to 12:00 UTC and refused as 'in the future' every morning before noon UTC."""
    from datetime import datetime, timedelta, timezone

    _seeded(client)
    now = datetime.now(timezone.utc)
    body = {"currency": "USD", "amount": "10.00", "payer_name": "ACME ROBOTICS INC"}
    r = client.post("/api/payments", json={**body, "external_ref": "TODAY-1", "received_at": now.date().isoformat()}, headers=OP)
    assert r.status_code == 200, r.text
    received = client.get(f"/api/deposits/{r.json()['deposit_id']}").json()["received_at"]
    assert datetime.fromisoformat(received.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
    two_days = (now + timedelta(days=2)).date().isoformat()
    r = client.post("/api/payments", json={**body, "external_ref": "LATER-1", "received_at": two_days}, headers=OP)
    assert r.status_code == 422 and "future" in r.json()["detail"]


def test_operator_can_apply_more_of_a_part_resolved_payment_to_the_same_invoice(client):
    """Regression (found by the randomized accuracy harness): a second operator allocation of the same
    escalated payment to the same invoice was refused with 'already allocated'."""
    _seeded(client)
    c = client.post("/api/customers", json={"name": "Tide Works", "country": "GB", "payer_names": ["TIDE WORKS LTD"],
                                             "refund_beneficiary": "Tide Works - UK account (synthetic)"}, headers=OP).json()
    inv = client.post("/api/invoices", json={"customer_id": c["id"], "currency": "GBP", "amount": "1000.00",
                                              "due_date": "2026-12-01", "description": "Retainer"}, headers=OP).json()
    dep = client.post("/api/payments", json={"external_ref": "TOPUP-1", "currency": "GBP", "amount": "600.00",
                                              "payer_name": "TIDE WORKS LTD", "reference": "no ref"}, headers=OP).json()["deposit_id"]
    body = {"action": "allocate", "invoice_id": inv["id"], "note": "confirmed by phone"}
    assert client.post(f"/api/deposits/{dep}/resolve", json={**body, "amount": "250.00"}, headers=OP).status_code == 200
    r = client.post(f"/api/deposits/{dep}/resolve", json={**body, "amount": "350.00"}, headers=OP)
    assert r.status_code == 200, r.text
    d = client.get(f"/api/deposits/{dep}").json()
    assert d["status"] == "matched" and d["buckets"]["allocated"] == 60_000 and d["buckets"]["unapplied"] == 0
    assert [a["amount_minor"] for a in d["allocations"]] == [60_000]
    assert client.get(f"/api/invoices/{inv['id']}").json()["remaining_minor"] == 40_000
    # Still bounded: once fully applied, the payment is no longer open for resolution.
    assert client.post(f"/api/deposits/{dep}/resolve", json={**body, "amount": "0.01"}, headers=OP).status_code == 409
    assert client.get("/api/ledger").json()["conservation"]["all_balanced"]
