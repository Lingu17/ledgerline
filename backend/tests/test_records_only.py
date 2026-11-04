"""A real company with no bank connected keeps records only: Ledgerline never pretends to send money for it. A person
records an approved refund they made in their own bank, with the same checks as a send."""
import pytest

from .conftest import new_client, signup
from .test_saas import _invite_and_join


@pytest.fixture
def real(app):
    c = new_client(app)
    signup(c, email="owner@records.test", org="Records Co", start_with="empty")
    assert c.post("/api/customers", json={"name": "Acme", "country": "GB", "payer_names": ["ACME LTD"],
                                          "refund_beneficiary": "Acme Ltd - GB29 NWBK 6016 1331 9268 19"}).status_code == 200
    r = c.post("/api/payments", json={"external_ref": "STMT-1", "currency": "GBP", "amount": "250.00", "payer_name": "ACME LTD", "reference": ""})
    assert r.status_code == 200, r.text
    dep = r.json()["deposit_id"]
    ap = c.post(f"/api/deposits/{dep}/return-to-sender").json()
    second = _invite_and_join(c, app, "second@records.test", "operator")
    assert second.post(f"/api/approvals/{ap['id']}/approve", json={"scope_hash": ap["scope_hash"]}).status_code == 200
    return {"owner": c, "second": second, "dep": dep, "approval": ap["id"]}


def test_executing_is_refused_and_nothing_moves(real):
    c = real["owner"]
    r = c.post(f"/api/approvals/{real['approval']}/execute")
    assert r.status_code == 409 and "no bank is connected" in r.text
    assert c.get("/api/operations").json() == []


def test_a_refund_made_outside_is_recorded_with_its_reference(real):
    c = real["owner"]
    path = f"/api/approvals/{real['approval']}/record-external"
    assert c.post(path, json={"paid_on": "2999-01-01", "reference": "FPS 123"}).status_code == 409  # future date
    assert c.post(path, json={"paid_on": "2026-11-03", "reference": "x"}).status_code == 409  # no real reference
    r = c.post(path, json={"paid_on": "2026-11-03", "reference": "FPS 4471-AB"})
    assert r.status_code == 200, r.text
    op = r.json()["operation"]
    assert op["status"] == "paid" and op["provider_id"] == "outside:FPS 4471-AB"
    assert c.get(f"/api/deposits/{real['dep']}").json()["status"] == "refunded"
    assert c.get("/api/ledger").json()["conservation"]["all_balanced"]
    rec = next(e for e in c.get("/api/audit", params={"q": "refund.recorded_outside"}).json())
    assert rec["detail"]["bank_reference"] == "FPS 4471-AB" and rec["detail"]["paid_on"] == "2026-11-03"
    assert c.post(path, json={"paid_on": "2026-11-03", "reference": "FPS 4471-AB"}).json()["replayed"] is True  # once only


def test_recording_is_for_companies_without_a_bank(client):
    client.post("/api/demo/step", json={"step": "deposits"})
    r = client.post("/api/approvals/APR-NOPE/record-external", json={"paid_on": "2026-11-03", "reference": "FPS 1"})
    assert r.status_code == 409 and "use Execute refund" in r.text  # a practice company keeps its simulated bank


def test_bill_payments_and_conversions_are_refused(real, app):
    c = real["owner"]
    r = c.post("/api/treasury/obligations", json={"payee": "Landlord", "currency": "GBP", "amount": "100.00",
                                                  "due_date": "2026-12-01", "priority": "normal"})
    assert r.status_code == 200, r.text
    r = c.post(f"/api/treasury/obligations/{r.json()['id']}/pay", json={"destination": "Landlord"})
    assert r.status_code == 409 and "Mark paid" in r.text
    from ledgerline import treasury
    from ledgerline.treasury import TreasuryError

    with pytest.raises(TreasuryError, match="no bank is connected"):
        treasury.execute_conversion(app.state.orgs.get(c.org_id), "Q-NOPE", "owner@records.test")


def test_proposing_a_return_names_what_and_whom_and_moves_the_status(app):
    c = new_client(app)
    signup(c, email="owner@return.test", org="Return Co", start_with="empty")
    c.post("/api/customers", json={"name": "Orchard Tea Co", "country": "GB", "payer_names": ["ORCHARD TEA"],
                                   "refund_beneficiary": "Orchard Tea Co - GB29 NWBK 6016 1331 9268 19"})
    dep = c.post("/api/payments", json={"external_ref": "S-9", "currency": "GBP", "amount": "40.00", "payer_name": "ORCHARD TEA",
                                        "reference": ""}).json()["deposit_id"]
    ap = c.post(f"/api/deposits/{dep}/return-to-sender", json={"note": "paid twice; confirmed by phone"}).json()
    assert ap["reason"] == "return payment with no reference to Orchard Tea Co: paid twice; confirmed by phone"
    assert c.get(f"/api/deposits/{dep}").json()["status"] == "refund_awaiting_approval"
    second = _invite_and_join(c, app, "second@return.test", "operator")
    assert second.post(f"/api/approvals/{ap['id']}/reject", json={"scope_hash": ap["scope_hash"]}).status_code == 200
    assert c.get(f"/api/deposits/{dep}").json()["status"] == "escalated"  # rejected: back with a person
