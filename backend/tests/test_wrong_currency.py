"""A payment in the wrong currency: convert only what the invoice needs, or hold it. Booked once, posted only when settled."""
from datetime import timedelta

import pytest

from ledgerline import audit, claude_reader, db, ledger, treasury, workspace, wrong_currency
from ledgerline.payouts import Paused, PayoutError
from ledgerline.providers.base import ProviderError
from ledgerline.reconcile import ESCALATED, deposit_buckets, ingest_deposit, invoice_views


@pytest.fixture
def world(settings):
    from ledgerline.api.app import build_context

    ctx = build_context(settings)
    for ccy, amount in (("USD", "100000"), ("EUR", "100000")):
        workspace.set_opening_balance(ctx, {"currency": ccy, "amount": amount}, "owner")
    cust = workspace.create_customer(ctx, {"name": "Orchard Tea", "country": "GB", "payer_names": ["ORCHARD TEA"], "refund_beneficiary": "Orchard"}, "op")
    day = (ctx.clock.now() + timedelta(days=20)).date().isoformat()
    inv = workspace.create_invoice(ctx, {"customer_id": cust["id"], "currency": "EUR", "amount": "1000", "due_date": day, "description": "Tea"}, "op")
    return ctx, cust["id"], inv["id"]


def pay(ctx, inv, amount_minor=200_000, ref="DEP-USD"):
    with ctx.conn() as conn, db.transaction(conn):
        dep, _ = ingest_deposit(conn, ctx, {"provider_ref": ref, "currency": "USD", "amount_minor": amount_minor, "payer_name": "ORCHARD TEA",
                                            "reference": inv, "received_at": "2026-11-01T00:00:00Z"}, source="manual_import")
    return dep


def state(ctx, dep, inv):
    with ctx.conn() as conn:
        return db.row(conn, "SELECT status FROM deposits WHERE id = ?", (dep,))["status"], deposit_buckets(conn, dep), invoice_views(conn)[inv].remaining_minor


def settle(ctx, op):
    return treasury._record_fx_outcome(ctx, op["id"], "settled", "prov-1", None)


def balanced(ctx):
    with ctx.conn() as conn:
        return ledger.conservation(conn)["all_balanced"] and audit.verify_chain(conn)["ok"]


def test_held_first_and_nothing_converts_by_itself(world):
    ctx, _, inv = world
    dep = pay(ctx, inv)
    status, buckets, remaining = state(ctx, dep, inv)
    assert status == ESCALATED and buckets["unapplied"] == 200_000 and remaining == 100_000
    with ctx.conn() as conn:
        assert not db.rows(conn, "SELECT id FROM deposit_conversions")


def test_recommends_converting_only_what_the_invoice_needs(world):
    ctx, _, inv = world
    o = wrong_currency.options(ctx, pay(ctx, inv))
    assert o["advice"] == "convert"
    row = o["invoices"][0]
    assert row["invoice_id"] == inv and row["buy_minor"] == 100_000 and row["covers_invoice"] and row["estimated_sell_minor"] < 200_000


def test_recommends_hold_when_a_bill_in_that_currency_is_due_and_short(world):
    ctx, _, inv = world
    day = (ctx.clock.now() + timedelta(days=2)).date().isoformat()
    workspace.create_obligation(ctx, {"payee": "US payroll", "currency": "USD", "amount": "100000", "due_date": day}, "op")
    assert wrong_currency.options(ctx, pay(ctx, inv))["advice"] == "hold"


def test_converts_settles_invoice_and_leaves_the_rest_with_a_person(world):
    ctx, _, inv = world
    dep = pay(ctx, inv)
    op = wrong_currency.convert(ctx, dep, inv, "alice")
    if op["status"] != "settled":
        op = settle(ctx, op)
    assert op["status"] == "settled"
    status, buckets, remaining = state(ctx, dep, inv)
    assert remaining == 0 and buckets["converted"] == op["amount_minor"]
    assert buckets["unapplied"] == 200_000 - op["amount_minor"] > 0 and status == ESCALATED
    assert balanced(ctx)


def test_a_payment_too_small_for_the_invoice_settles_part_of_it(world):
    ctx, _, inv = world
    dep = pay(ctx, inv, amount_minor=100_000)  # USD 1,000 cannot buy EUR 1,000 at the practice rate
    op = wrong_currency.convert(ctx, dep, inv, "alice")
    if op["status"] != "settled":
        settle(ctx, op)
    _, buckets, remaining = state(ctx, dep, inv)
    assert 0 < remaining < 100_000 and buckets["unapplied"] >= 0 and balanced(ctx)


def test_money_is_reserved_while_in_flight_and_released_on_failure(world, monkeypatch):
    ctx, _, inv = world
    dep = pay(ctx, inv)
    monkeypatch.setattr(ctx.provider, "create_conversion", lambda **_k: (_ for _ in ()).throw(ProviderError("refused")))
    with pytest.raises(PayoutError, match="stays held"):
        wrong_currency.convert(ctx, dep, inv, "alice")
    status, buckets, remaining = state(ctx, dep, inv)
    assert status == ESCALATED and buckets["unapplied"] == 200_000 and remaining == 100_000 and balanced(ctx)


def test_second_conversion_refused_while_one_is_live(world, monkeypatch):
    ctx, _, inv = world
    dep = pay(ctx, inv)
    real = ctx.provider.create_conversion

    class Pending:
        status, provider_id = "processing", "prov-2"
    monkeypatch.setattr(ctx.provider, "create_conversion", lambda **_k: Pending())
    wrong_currency.convert(ctx, dep, inv, "alice")
    assert state(ctx, dep, inv)[2] == 0  # reserved: another payment cannot settle the same balance
    monkeypatch.setattr(ctx.provider, "create_conversion", real)
    with pytest.raises(PayoutError):
        wrong_currency.convert(ctx, dep, inv, "bob")
    with ctx.conn() as conn:
        assert len(db.rows(conn, "SELECT id FROM deposit_conversions")) == 1


def test_another_customers_invoice_and_clean_deposits_are_refused(world):
    ctx, _, inv = world
    other = workspace.create_customer(ctx, {"name": "Other Co", "country": "GB", "payer_names": ["OTHER CO"], "refund_beneficiary": "Other"}, "op")
    day = (ctx.clock.now() + timedelta(days=20)).date().isoformat()
    theirs = workspace.create_invoice(ctx, {"customer_id": other["id"], "currency": "EUR", "amount": "50", "due_date": day, "description": "x"}, "op")
    dep = pay(ctx, inv)
    with pytest.raises(PayoutError, match="another customer"):
        wrong_currency.convert(ctx, dep, theirs["id"], "alice")


def test_pause_blocks_conversion(world):
    ctx, _, inv = world
    dep = pay(ctx, inv)
    with ctx.conn() as conn, db.transaction(conn):
        db.set_setting(conn, "money_out_paused", True)
    with pytest.raises(Paused):
        wrong_currency.convert(ctx, dep, inv, "alice")


def test_claude_conversion_tool_is_typed_and_advisory():
    good = {"tool": "propose_conversion", "input": {"for_invoice_id": "INV-2252", "rationale": "paid in USD by mistake"}}
    assert claude_reader.typed_proposal(good) == good
    bad = {"tool": "propose_conversion", "input": {"for_invoice_id": "2252; drop", "rationale": "x"}}
    assert claude_reader.typed_proposal(bad)["tool"] == "escalate"
    amounts = {"tool": "propose_conversion", "input": {"for_invoice_id": "INV-2252", "rationale": "x", "amount": "9000"}}
    assert claude_reader.typed_proposal(amounts)["tool"] == "escalate"  # the model can never state an amount


def test_viewer_cannot_convert(client, app):
    from .test_saas import _invite_and_join

    viewer = _invite_and_join(client, app, "v9@northbeam.test", "viewer")
    assert viewer.post("/api/deposits/DEP-1/wrong-currency/convert", json={"invoice_id": "INV-1"}).status_code == 403
