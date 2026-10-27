"""Treasury converts only the deficit, respects reserves and single-use expiring quotes; ledger conserves per currency."""
from datetime import timedelta

import pytest

from ledgerline import db, ledger, treasury
from ledgerline.demo import run_step
from ledgerline.payouts import Paused
from ledgerline.reconcile import ReconcileError, _allocate, invoice_views

from .conftest import one, run_to


@pytest.fixture
def after_agents(ctx):
    run_to(ctx, "agents")
    return ctx


def test_deficit_accounts_for_cash_reserve_held_funds_and_obligation(after_agents):
    with after_agents.conn() as conn:
        plan = treasury.plan_for_obligation(conn, after_agents, "OBL-EUR-HOSTING")
    # EUR cash 1,500 + 4,985 + 1,750 = 8,235; reserve 2,000; unidentified 1,750 held; bill 9,000
    assert plan["target"]["cash"] == 823_500
    assert plan["target"]["unapplied_held"] == 175_000
    assert plan["deficit"] == 451_500
    assert plan["source_currency"] == "USD"


def test_conversion_buys_exactly_the_deficit_and_keeps_reserves(after_agents):
    quote = treasury.create_quote(after_agents, "OBL-EUR-HOSTING", "op")
    assert quote["quote"]["buy_amount_minor"] == 451_500
    assert quote["source_free_after"] >= 0
    treasury.execute_conversion(after_agents, quote["quote"]["id"], "op")
    with after_agents.conn() as conn:
        pos = treasury.wallet_position(conn, after_agents)
        assert pos["EUR"]["free_after_commitments"] == 0
        assert pos["USD"]["cash"] - pos["USD"]["reserve"] > 0
        assert treasury.plan_for_obligation(conn, after_agents, "OBL-EUR-HOSTING")["deficit"] == 0
        assert ledger.conservation(conn)["all_balanced"]


def test_quote_is_single_use(after_agents):
    quote = treasury.create_quote(after_agents, "OBL-EUR-HOSTING", "op")
    treasury.execute_conversion(after_agents, quote["quote"]["id"], "op")
    with pytest.raises(treasury.TreasuryError, match="single-use"):
        treasury.execute_conversion(after_agents, quote["quote"]["id"], "op")


def test_expired_quote_cannot_execute(after_agents):
    quote = treasury.create_quote(after_agents, "OBL-EUR-HOSTING", "op")
    after_agents.clock.advance(timedelta(minutes=2))
    with pytest.raises(treasury.TreasuryError, match="expired"):
        treasury.execute_conversion(after_agents, quote["quote"]["id"], "op")
    assert one(after_agents, "SELECT COUNT(*) AS n FROM operations WHERE kind='fx_conversion'")["n"] == 0


def test_stale_quote_after_position_change_rejected(after_agents):
    quote = treasury.create_quote(after_agents, "OBL-EUR-HOSTING", "op")
    with after_agents.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE obligations SET amount_minor = 950000 WHERE id = 'OBL-EUR-HOSTING'")
    with pytest.raises(treasury.TreasuryError, match="shortfall is now"):
        treasury.execute_conversion(after_agents, quote["quote"]["id"], "op")


def test_reserve_breach_refused(after_agents):
    with after_agents.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE obligations SET amount_minor = 2900000 WHERE id = 'OBL-EUR-HOSTING'")
    with pytest.raises(treasury.TreasuryError, match="no currency has enough surplus"):
        treasury.create_quote(after_agents, "OBL-EUR-HOSTING", "op")


def test_pause_blocks_conversion(after_agents):
    quote = treasury.create_quote(after_agents, "OBL-EUR-HOSTING", "op")
    with after_agents.conn() as conn, db.transaction(conn):
        db.set_setting(conn, "money_out_paused", True)
    with pytest.raises(Paused):
        treasury.execute_conversion(after_agents, quote["quote"]["id"], "op")


def test_partial_allocation_conserves_and_tracks_remaining(after_agents):
    with after_agents.conn() as conn:
        c = ledger.conservation(conn)["currencies"]["GBP"]
        inv = invoice_views(conn)["INV-2260"]
    assert inv.remaining_minor == 120_000  # 3,600 - 2,400
    assert c["deposits"] == 240_000 + 480_000
    assert c["allocated"] == 240_000 and c["unapplied"] == 480_000 and c["balanced"]
    link = one(after_agents, "SELECT * FROM payment_links WHERE invoice_id = 'INV-2260'")
    assert link["amount_minor"] == 120_000 and link["status"] == "draft_fallback"


def test_invoice_cannot_be_overallocated_or_allocated_twice(after_agents):
    with after_agents.conn() as conn:
        d = db.row(conn, "SELECT * FROM deposits WHERE id = 'DEP-1004'")
    with pytest.raises(ReconcileError, match="overpay"):
        with after_agents.conn() as conn, db.transaction(conn):
            _allocate(conn, "t", d, "INV-2252", 1)  # already settled (with fee write-off)
    with after_agents.conn() as conn:
        d1 = db.row(conn, "SELECT * FROM deposits WHERE id = 'DEP-1001'")
    with pytest.raises(ReconcileError):
        with after_agents.conn() as conn, db.transaction(conn):
            _allocate(conn, "t", d1, "INV-2231", 1)
    with after_agents.conn() as conn:
        assert ledger.conservation(conn)["all_balanced"]


def test_fee_writeoff_settles_invoice_without_touching_deposit_cash(after_agents):
    with after_agents.conn() as conn:
        eur = ledger.conservation(conn)["currencies"]["EUR"]
        assert invoice_views(conn)["INV-2252"].remaining_minor == 0
    assert eur["bank_fee_writeoffs"] == 1_500
    assert eur["allocated"] == 498_500


def test_policy_and_pause_persist_across_restart(settings):
    from ledgerline.api.app import build_context
    from ledgerline.context import validate_policy

    c1 = build_context(settings)
    run_step(c1, "seed", "t")
    policy = validate_policy({"refund_auto_limit_minor": {"USD": 1, "EUR": 2, "GBP": 3}})
    with c1.conn() as conn, db.transaction(conn):
        db.set_setting(conn, "policy", policy)
        db.set_setting(conn, "money_out_paused", True)
    run_step(c1, "seed", "t")  # demo reset keeps policy and pause
    c2 = build_context(settings)
    with c2.conn() as conn:
        assert c2.paused(conn) is True
        assert c2.policy(conn)["refund_auto_limit_minor"]["GBP"] == 3
