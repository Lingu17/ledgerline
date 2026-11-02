"""Bringing cash in early: capped discount, one offer, booked only when paid, ledger balanced, plan reopened."""
from datetime import timedelta

import pytest

from ledgerline import audit, db, early_pay, ledger, treasury, workspace
from ledgerline.payouts import PayoutError
from ledgerline.providers.base import PaymentLinkResult, ProviderAmbiguous, ProviderUnsupported

from .conftest import q
from .test_saas import _invite_and_join


@pytest.fixture
def world(settings):
    from ledgerline.api.app import build_context

    ctx = build_context(settings)
    workspace.set_opening_balance(ctx, {"currency": "EUR", "amount": "2000"}, "owner")  # exactly the reserve
    cust = workspace.create_customer(ctx, {"name": "Orchard Tea", "country": "GB", "payer_names": ["ORCHARD TEA"], "refund_beneficiary": "Orchard"}, "op")
    day = lambda n: (ctx.clock.now() + timedelta(days=n)).date().isoformat()  # noqa: E731
    inv = workspace.create_invoice(ctx, {"customer_id": cust["id"], "currency": "EUR", "amount": "10000", "due_date": day(21), "description": "Tea"}, "op")
    bill = workspace.create_obligation(ctx, {"payee": "Tax", "currency": "EUR", "amount": "5000", "due_date": day(2)}, "op")
    treasury.refresh_decisions(ctx, "test")
    return ctx, inv["id"], bill["id"]


class FakeSandbox:
    """Stands in for the connected account's payment-link calls."""
    def __init__(self, fail=None):
        self.fail, self.calls, self.paid = fail, [], False

    def create_payment_link(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise self.fail
        return PaymentLinkResult("plink_1", "https://pay.sandbox.airwallex.com/abc")

    def payment_link_paid(self, provider_id):
        return self.paid


def balanced(ctx):
    with ctx.conn() as conn:
        return ledger.conservation(conn)["all_balanced"]


def decision(ctx, bill):
    return {d["obligation_id"]: d for d in treasury.refresh_decisions(ctx, "t")["decisions"]}[bill]["decision"]


def test_options_price_the_gap(world):
    ctx, inv, _ = world
    o = early_pay.options(ctx)
    assert o["gaps"] == {"EUR": 500_000}
    row = o["options"][0]
    assert (row["invoice_id"], row["discount_minor"], row["cash_minor"], row["closes_gap"]) == (inv, 15_000, 985_000, True)


def test_paid_offer_books_discount_and_cash_and_reopens_the_bill(world):
    ctx, inv, bill = world
    assert decision(ctx, bill) == "escalate"
    offer = early_pay.create_offer(ctx, inv, 150, "alice")
    assert offer["status"] == "open" and q(ctx, "SELECT COUNT(*) AS n FROM deposits")[0]["n"] == 0
    paid = early_pay.practice_paid(ctx, offer["id"], "alice")
    assert paid["status"] == "paid" and paid["deposit_id"]
    views = q(ctx, "SELECT status FROM deposits WHERE id = ?", (paid["deposit_id"],))
    assert views[0]["status"] == "matched"
    with ctx.conn() as conn:
        from ledgerline.reconcile import invoice_views

        assert invoice_views(conn)[inv].remaining_minor == 0
        assert treasury.wallet_position(conn, ctx)["EUR"]["cash"] == 200_000 + 985_000
    assert balanced(ctx) and decision(ctx, bill) == "fund"
    with ctx.conn() as conn:
        assert audit.verify_chain(conn)["ok"]


def test_discount_is_capped_by_policy(world):
    ctx, inv, _ = world
    with pytest.raises(PayoutError, match="at most 200"):
        early_pay.create_offer(ctx, inv, 201, "alice")
    with pytest.raises(PayoutError):
        early_pay.create_offer(ctx, inv, 0, "alice")


def test_one_live_offer_per_invoice(world):
    ctx, inv, _ = world
    early_pay.create_offer(ctx, inv, 100, "alice")
    with pytest.raises(PayoutError, match="already has"):
        early_pay.create_offer(ctx, inv, 100, "bob")
    assert all(o["invoice_id"] != inv for o in early_pay.options(ctx)["options"])


def test_overdue_or_unknown_invoice_refused(world):
    ctx, inv, _ = world
    with pytest.raises(PayoutError):
        early_pay.create_offer(ctx, "INV-9999", 100, "alice")
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE invoices SET due_at = '2020-01-01T00:00:00Z' WHERE id = ?", (inv,))
    with pytest.raises(PayoutError, match="already due"):
        early_pay.create_offer(ctx, inv, 100, "alice")


def test_payment_is_booked_once(world):
    ctx, inv, _ = world
    offer = early_pay.create_offer(ctx, inv, 100, "alice")
    early_pay.practice_paid(ctx, offer["id"], "alice")
    early_pay.practice_paid(ctx, offer["id"], "alice")
    assert q(ctx, "SELECT COUNT(*) AS n FROM deposits")[0]["n"] == 1
    assert q(ctx, "SELECT COUNT(*) AS n FROM invoice_adjustments")[0]["n"] == 1
    assert balanced(ctx)


def test_changed_invoice_gets_no_discount(world):
    ctx, inv, _ = world
    offer = early_pay.create_offer(ctx, inv, 100, "alice")
    workspace.adjust_invoice(ctx, inv, {"kind": "increase", "amount": "500", "reason": "extra goods"}, "alice")
    paid = early_pay.practice_paid(ctx, offer["id"], "alice")
    assert "no discount" in paid["note"]
    assert q(ctx, "SELECT COUNT(*) AS n FROM invoice_adjustments WHERE delta_minor < 0")[0]["n"] == 0
    assert balanced(ctx)


def test_connected_account_creates_a_real_link_and_waits_for_airwallex(world):
    ctx, inv, _ = world
    ctx.sandbox = FakeSandbox()
    offer = early_pay.create_offer(ctx, inv, 150, "alice")
    assert offer["url"].startswith("https://") and ctx.sandbox.calls[0]["amount_minor"] == 985_000 and ctx.sandbox.calls[0]["reference"] == inv
    assert early_pay.check(ctx, offer["id"], "alice")["status"] == "open"
    with pytest.raises(PayoutError, match="reported by Airwallex"):
        early_pay.practice_paid(ctx, offer["id"], "alice")
    ctx.sandbox.paid = True
    assert early_pay.check(ctx, offer["id"], "alice")["status"] == "paid"
    assert q(ctx, "SELECT source FROM deposits")[0]["source"] == "airwallex_payment_link" and balanced(ctx)


def test_link_refused_leaves_no_live_offer_and_no_url(world):
    ctx, inv, _ = world
    ctx.sandbox = FakeSandbox(fail=ProviderUnsupported("configuration_error"))
    o = early_pay.create_offer(ctx, inv, 150, "alice")
    assert o["status"] == "failed" and o["url"] is None
    ctx.sandbox = FakeSandbox()
    assert early_pay.create_offer(ctx, inv, 150, "alice")["status"] == "open"


def test_uncertain_link_blocks_a_second_one(world):
    ctx, inv, _ = world
    ctx.sandbox = FakeSandbox(fail=ProviderAmbiguous("timeout"))
    assert early_pay.create_offer(ctx, inv, 150, "alice")["status"] == "unknown"
    with pytest.raises(PayoutError, match="already has"):
        early_pay.create_offer(ctx, inv, 150, "alice")


def test_api_viewer_blocked_and_practice_reset_clears_offers(client, app):
    client.post("/api/demo/step", json={"step": "deposits"})
    client.post("/api/treasury/practice-squeeze")
    opt = client.get("/api/treasury/early-pay/options").json()
    squeeze = next(o for o in opt["options"] if o["invoice_id"] == "INV-2901")
    assert squeeze["closes_gap"]
    viewer = _invite_and_join(client, app, "v3@northbeam.test", "viewer")
    assert viewer.post("/api/invoices/INV-2901/early-pay", json={"discount_bps": 100}).status_code == 403
    r = client.post("/api/invoices/INV-2901/early-pay", json={"discount_bps": 150})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/treasury/early-pay/{r.json()['id']}/practice-paid").status_code == 200
    plan = {d["obligation_id"]: d["decision"] for d in client.get("/api/treasury/decisions").json()["decisions"]}
    assert not {plan["OBL-SQUEEZE-TAX"], plan["OBL-SQUEEZE-AGENCY"]} & {"defer", "escalate"}  # the early cash closed the gap
    assert client.get("/api/ledger").json()["conservation"]["all_balanced"]
    assert client.get("/api/audit/verify").json()["ok"]
    assert client.post("/api/demo/step", json={"step": "seed"}).status_code == 200
    assert client.get("/api/treasury/early-pay").json() == []
