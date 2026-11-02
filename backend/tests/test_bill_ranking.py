"""Short-cash bill decisions: rank, fund, convert, defer or escalate; new cash reopens only what it changes."""
from datetime import timedelta

import pytest

from ledgerline import db, ledger, treasury, workspace
from ledgerline.clock import iso

from .conftest import q


@pytest.fixture
def empty(settings):
    from ledgerline.api.app import build_context

    return build_context(settings)


def day(ctx, n):
    return (ctx.clock.now() + timedelta(days=n)).date().isoformat()


def setup_cash(ctx, **balances):
    for ccy, amount in balances.items():
        workspace.set_opening_balance(ctx, {"currency": ccy, "amount": amount}, "owner")


def bill(ctx, payee, ccy, amount, due, **extra):
    return workspace.create_obligation(ctx, {"payee": payee, "currency": ccy, "amount": amount, "due_date": day(ctx, due), **extra}, "op")["id"]


def by_id(result):
    return {d["obligation_id"]: d for d in result["decisions"]}


def test_critical_bill_is_funded_before_an_earlier_normal_bill(empty):
    # EUR reserve is 2,000, so 5,000 leaves 3,000 to spend. USD and GBP have nothing above their reserves.
    setup_cash(empty, EUR="5000")
    early = bill(empty, "Hosting", "EUR", "3000", 1)
    payroll = bill(empty, "Payroll", "EUR", "3000", 5, priority="critical")
    d = by_id(treasury.refresh_decisions(empty, "test"))
    assert d[payroll]["rank"] == 1 and d[payroll]["decision"] == "fund"
    assert d[early]["decision"] == "escalate" and d[early]["shortfall_minor"] == 300_000


def test_short_bill_converts_only_the_shortfall(empty):
    setup_cash(empty, EUR="3000", USD="20000")  # 1,000 EUR free; 15,000 USD free above reserve
    b = bill(empty, "Supplier", "EUR", "1500", 2)
    d = by_id(treasury.refresh_decisions(empty, "test"))[b]
    assert (d["decision"], d["shortfall_minor"], d["source_currency"]) == ("convert", 50_000, "USD")


def test_one_surplus_is_not_promised_to_two_bills(empty):
    setup_cash(empty, USD="6000", EUR="2000")  # 1,000 USD surplus only; EUR sits exactly at its reserve
    first = bill(empty, "First", "EUR", "800", 1)
    second = bill(empty, "Second", "EUR", "800", 2)
    d = by_id(treasury.refresh_decisions(empty, "test"))
    assert d[first]["decision"] == "convert"
    assert d[second]["decision"] == "escalate"


def test_flexible_bill_defers_only_when_it_has_a_permitted_date(empty):
    setup_cash(empty, EUR="2000")
    can = bill(empty, "Agency", "EUR", "500", 2, priority="flexible", defer_until=day(empty, 20))
    cannot = bill(empty, "Tax", "EUR", "500", 2)
    d = by_id(treasury.refresh_decisions(empty, "test"))
    assert d[can]["decision"] == "defer"
    assert d[cannot]["decision"] == "escalate"


def test_shortfall_includes_refilling_the_reserve_and_matches_the_quote_plan(empty):
    b = bill(empty, "Payroll", "EUR", "9000", 2, priority="critical")
    d = by_id(treasury.refresh_decisions(empty, "test"))[b]
    with empty.conn() as conn:
        assert d["shortfall_minor"] == treasury.plan_for_obligation(conn, empty, b)["deficit"] == 1_100_000


def test_critical_bill_cannot_be_given_a_later_date(empty):
    with pytest.raises(workspace.InputError, match="critical"):
        bill(empty, "Payroll", "EUR", "500", 2, priority="critical", defer_until=day(empty, 20))


def test_deposit_reopens_only_the_decisions_it_changes(empty):
    setup_cash(empty, EUR="2000", GBP="2000")  # EUR has nothing free; GBP has 500 free
    eur = bill(empty, "EUR bill", "EUR", "1000", 2)
    gbp = bill(empty, "GBP bill", "GBP", "100", 2)
    first = by_id(treasury.refresh_decisions(empty, "test"))
    assert first[eur]["decision"] == "escalate" and first[gbp]["decision"] == "fund"
    cust = workspace.create_customer(empty, {"name": "Orchard Tea", "country": "GB", "payer_names": ["ORCHARD TEA"], "refund_beneficiary": "Orchard"}, "op")
    inv = workspace.create_invoice(empty, {"customer_id": cust["id"], "currency": "EUR", "amount": "1000", "due_date": day(empty, 5), "description": "Tea"}, "op")
    dep = workspace.record_manual_payment(empty, {"external_ref": "R1", "currency": "EUR", "amount": "1000", "payer_name": "ORCHARD TEA", "reference": inv["id"]}, "op")["deposit_id"]
    r = treasury.refresh_decisions(empty, "deposit received")
    assert r["changed"] == [{"obligation_id": eur, "from": "escalate", "to": "fund"}]
    assert r["unchanged"] == 1
    assert by_id(r)[gbp]["version"] == 1 and by_id(r)[eur]["version"] == 2
    trail = q(empty, "SELECT * FROM audit_events WHERE action = 'treasury.decision' AND entity_id = ?", (gbp,))
    assert len(trail) == 1 and dep


def test_repeat_review_writes_nothing_new(empty):
    setup_cash(empty, EUR="2000")
    bill(empty, "Bill", "EUR", "100", 2)
    treasury.refresh_decisions(empty, "test")
    before = len(q(empty, "SELECT id FROM audit_events"))
    assert treasury.refresh_decisions(empty, "test")["changed"] == []
    assert len(q(empty, "SELECT id FROM audit_events")) == before


def test_applied_deferral_moves_the_date_and_clears_the_shortfall(empty):
    setup_cash(empty, EUR="2000")
    b = bill(empty, "Agency", "EUR", "500", 2, priority="flexible", defer_until=day(empty, 30))
    treasury.refresh_decisions(empty, "test")
    r = treasury.apply_deferral(empty, b, "op")
    assert b not in by_id(r)  # now beyond the 14-day window
    row = q(empty, "SELECT due_at FROM obligations WHERE id = ?", (b,))[0]
    assert row["due_at"] > iso(empty.clock.now() + timedelta(days=29))


def test_defer_is_refused_when_the_decision_is_something_else(empty):
    setup_cash(empty, EUR="5000")
    b = bill(empty, "Agency", "EUR", "500", 2, priority="flexible", defer_until=day(empty, 30))
    treasury.refresh_decisions(empty, "test")
    with pytest.raises(treasury.TreasuryError):
        treasury.apply_deferral(empty, b, "op")


def test_marking_paid_reduces_cash_and_keeps_the_ledger_balanced(empty):
    setup_cash(empty, EUR="5000")
    b = bill(empty, "Hosting", "EUR", "500", 2)
    treasury.mark_bill_paid(empty, b, "op")
    with empty.conn() as conn:
        assert treasury.wallet_position(conn, empty)["EUR"]["cash"] == 450_000
        assert ledger.conservation(conn)["all_balanced"]
    with pytest.raises(treasury.TreasuryError):
        treasury.mark_bill_paid(empty, b, "op")


def test_missing_rates_escalate_instead_of_guessing(empty):
    setup_cash(empty, EUR="3000", USD="20000")
    b = bill(empty, "Supplier", "EUR", "1500", 2)
    with empty.conn() as conn:
        assert {d["obligation_id"]: d for d in treasury.rank_bills(conn, empty, {})}[b]["decision"] == "escalate"


def test_practice_squeeze_shows_all_four_and_a_payment_reopens_only_what_changes(client, app):
    from .test_saas import _invite_and_join  # noqa: F401 - same fixtures

    for step in ("deposits", "links", "agents"):
        client.post("/api/demo/step", json={"step": step})
    r = client.post("/api/treasury/practice-squeeze")
    assert r.status_code == 200, r.text
    d = by_id(r.json())
    assert {x["decision"] for x in d.values()} >= {"fund", "convert", "defer", "escalate"}
    assert d["OBL-SQUEEZE-PAYROLL"]["rank"] == 1 and d["OBL-SQUEEZE-PAYROLL"]["decision"] == "fund"
    assert d["OBL-SQUEEZE-TAX"]["decision"] == "escalate" and d["OBL-SQUEEZE-AGENCY"]["decision"] == "defer"
    assert client.post("/api/treasury/practice-squeeze").status_code == 409

    open_gbp = next(i for i in client.get("/api/invoices?status=outstanding").json() if i["id"] == "INV-2260")
    amount = f"{open_gbp['remaining_minor'] / 100:.2f}"
    payer = next(c for c in client.get("/api/customers").json() if c["id"] == open_gbp["customer_id"])["payer_names"][0]
    pay = client.post("/api/payments", json={"external_ref": "SQUEEZE-1", "currency": "GBP", "amount": amount, "payer_name": payer, "reference": open_gbp["id"]})
    assert pay.status_code == 200, pay.text
    after = client.get("/api/treasury/decisions").json()
    changed = {c["obligation_id"]: c["to"] for c in after["changed"]}
    assert changed.get("OBL-SQUEEZE-TAX") in ("fund", "convert")
    assert "OBL-SQUEEZE-PAYROLL" not in changed and "OBL-SQUEEZE-AGENCY" not in changed


def test_convert_decision_buys_only_that_bills_shortfall_once(empty):
    setup_cash(empty, EUR="2500", USD="20000")  # EUR 500 free, USD 15,000 free
    first = bill(empty, "First", "EUR", "800", 1, priority="critical")
    bill(empty, "Too big", "EUR", "90000", 2)
    d = by_id(treasury.refresh_decisions(empty, "test"))[first]
    assert d["decision"] == "convert" and d["shortfall_minor"] == 30_000
    q = treasury.create_quote(empty, first, "op")
    assert q["quote"]["buy_amount_minor"] == 30_000 and q["quote"]["sell_currency"] == "USD"
    treasury.execute_conversion(empty, q["quote"]["id"], "op")
    d = by_id(treasury.refresh_decisions(empty, "test"))[first]
    assert d["decision"] == "fund"  # pending cover counts; no second conversion is proposed
    with empty.conn() as conn:
        assert ledger.conservation(conn)["all_balanced"]


def test_ring_fenced_cash_makes_a_funded_wallet_short_and_new_cash_still_counts(empty):
    setup_cash(empty, EUR="10000000")
    b = bill(empty, "Supplier", "EUR", "5000", 2)
    assert by_id(treasury.refresh_decisions(empty, "test"))[b]["decision"] == "fund"
    with empty.conn() as conn, db.transaction(conn):
        from ledgerline.context import validate_policy

        db.set_setting(conn, "policy", validate_policy({"ring_fenced_minor": {"USD": 0, "EUR": 999_600_000, "GBP": 0}}))
    d = by_id(treasury.refresh_decisions(empty, "test"))[b]
    assert d["decision"] == "escalate" and d["shortfall_minor"] == 300_000  # 4,000 left - 2,000 reserve; bill 5,000
    with empty.conn() as conn:
        p = treasury.wallet_position(conn, empty)["EUR"]
        assert p["cash"] == 1_000_000_000 and p["ring_fenced"] == 999_600_000  # the real balance is still shown
    cust = workspace.create_customer(empty, {"name": "Orchard", "country": "GB", "payer_names": ["ORCHARD"], "refund_beneficiary": "Orchard"}, "op")
    inv = workspace.create_invoice(empty, {"customer_id": cust["id"], "currency": "EUR", "amount": "3000", "due_date": day(empty, 5), "description": "x"}, "op")
    workspace.record_manual_payment(empty, {"external_ref": "R9", "currency": "EUR", "amount": "3000", "payer_name": "ORCHARD", "reference": inv["id"]}, "op")
    assert by_id(treasury.refresh_decisions(empty, "deposit"))[b]["decision"] == "fund"


def test_squeeze_is_refused_for_a_real_company(app):
    from fastapi.testclient import TestClient

    from .conftest import signup

    c = TestClient(app)
    signup(c, email="o@real.test", org="Real", start_with="empty")
    assert c.post("/api/treasury/practice-squeeze").status_code == 409


def test_viewer_cannot_defer_or_mark_paid(client, app):
    from .test_saas import _invite_and_join

    v = _invite_and_join(client, app, "view@northbeam.test", "viewer")
    assert v.post("/api/treasury/obligations/OBL-EUR-HOSTING/mark-paid").status_code == 403
    assert v.post("/api/treasury/obligations/OBL-EUR-HOSTING/defer").status_code == 403



def released_setup(empty, **cash):
    setup_cash(empty, **cash)
    cust = workspace.create_customer(empty, {"name": "Orchard Tea", "country": "GB", "payer_names": ["ORCHARD TEA"], "refund_beneficiary": "Orchard"}, "op")
    return workspace.create_invoice(empty, {"customer_id": cust["id"], "currency": "EUR", "amount": "10000", "due_date": day(empty, 20), "description": "Tea"}, "op")["id"]


def test_bill_that_releases_more_cash_than_it_costs_goes_first(empty):
    inv = released_setup(empty, EUR="5000")
    early = bill(empty, "Hosting", "EUR", "3000", 1)
    supplier = bill(empty, "Supplier", "EUR", "3000", 5, unlocks_invoice_id=inv)
    d = by_id(treasury.refresh_decisions(empty, "t"))
    assert d[supplier]["rank"] == 1 and d[supplier]["decision"] == "fund" and inv in d[supplier]["reason"]
    assert d[early]["rank"] == 2 and d[early]["decision"] == "escalate"


def test_critical_bill_still_beats_one_that_releases_cash(empty):
    inv = released_setup(empty, EUR="5000")
    supplier = bill(empty, "Supplier", "EUR", "3000", 1, unlocks_invoice_id=inv)
    payroll = bill(empty, "Payroll", "EUR", "3000", 5, priority="critical")
    d = by_id(treasury.refresh_decisions(empty, "t"))
    assert d[payroll]["rank"] == 1 and d[supplier]["rank"] == 2


def test_releasing_less_than_the_bill_costs_does_not_change_the_order(empty):
    inv = released_setup(empty, EUR="50000")
    early = bill(empty, "Hosting", "EUR", "3000", 1)
    big = bill(empty, "Machine", "EUR", "20000", 5, unlocks_invoice_id=inv)
    d = by_id(treasury.refresh_decisions(empty, "t"))
    assert d[early]["rank"] == 1 and d[big]["rank"] == 2


def test_unknown_released_invoice_is_refused(empty):
    with pytest.raises(workspace.InputError):
        bill(empty, "Supplier", "EUR", "100", 2, unlocks_invoice_id="INV-9999")


def test_plan_with_released_invoice_replays_identically(empty):
    inv = released_setup(empty, EUR="5000")
    bill(empty, "Supplier", "EUR", "3000", 5, unlocks_invoice_id=inv)
    treasury.refresh_decisions(empty, "t")
    run = treasury.list_plan_runs(empty)[0]
    assert treasury.replay_plan_run(empty, run["id"])["identical"]
