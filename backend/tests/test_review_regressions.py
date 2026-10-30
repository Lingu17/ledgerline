"""Regressions for docs/archive/CODEX_REVIEW_FINDINGS.md (first pass), one section per finding."""
import gc
import json
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from ledgerline import crypto, db, ledger, payouts, treasury, webhooks
from ledgerline.clock import Clock, iso
from ledgerline.evidence import verify
from ledgerline.money import MoneyError, to_minor
from ledgerline.payer_agents.keys import ensure_keys, key_location
from ledgerline.payouts import PayoutError
from ledgerline.providers.base import TransferResult
from ledgerline.providers.local import LocalBank
from ledgerline.reconcile import ReconcileError, invoice_views, key_registry, record_agent_answer

from .conftest import OP, one, q, run_to


def _cash(ctx, ccy):
    with ctx.conn() as conn:
        return ledger.conservation(conn)["currencies"][ccy]


# 1. FX finality: only a verified SETTLED status moves cash ------------------------------------
@pytest.mark.parametrize("fault", ["SCHEDULED", "OVERDUE"])
def test_fx_not_settled_does_not_move_cash_and_reconciles_later(ctx, fault):
    run_to(ctx, "agents")
    eur_before, usd_before = _cash(ctx, "EUR")["wallet_cash"], _cash(ctx, "USD")["wallet_cash"]
    quote = treasury.create_quote(ctx, "OBL-EUR-HOSTING", "op")
    ctx.local_bank.next_conversion_fault = fault
    op = treasury.execute_conversion(ctx, quote["quote"]["id"], "op")
    assert op["status"] == "processing"
    assert _cash(ctx, "EUR")["wallet_cash"] == eur_before and _cash(ctx, "USD")["wallet_cash"] == usd_before
    with ctx.conn() as conn:
        pos = treasury.wallet_position(conn, ctx)
    assert pos["USD"]["fx_out_reserved"] == quote["quote"]["sell_amount_minor"]
    assert pos["EUR"]["fx_in_pending"] == 451_500
    ctx.local_bank.simulate_conversion_status(op["provider_id"], "SETTLED")
    op = treasury.sync_conversion(ctx, op["id"])
    assert op["status"] == "settled"
    assert _cash(ctx, "EUR")["wallet_cash"] == eur_before + 451_500
    with ctx.conn() as conn:
        assert ledger.conservation(conn)["all_balanced"]


def test_fx_cancelled_releases_reservation_without_cash(ctx):
    run_to(ctx, "agents")
    usd_before = _cash(ctx, "USD")["wallet_cash"]
    quote = treasury.create_quote(ctx, "OBL-EUR-HOSTING", "op")
    ctx.local_bank.next_conversion_fault = "CANCELLED"
    with pytest.raises(PayoutError):
        treasury.execute_conversion(ctx, quote["quote"]["id"], "op")
    assert _cash(ctx, "USD")["wallet_cash"] == usd_before
    with ctx.conn() as conn:
        assert treasury.wallet_position(conn, ctx)["USD"]["fx_out_reserved"] == 0
        assert treasury.plan_for_obligation(conn, ctx, "OBL-EUR-HOSTING")["deficit"] == 451_500


# 2. In-flight FX reservation blocks double funding --------------------------------------------
def test_second_quote_cannot_fund_same_deficit_while_first_in_flight(ctx):
    run_to(ctx, "agents")
    q1 = treasury.create_quote(ctx, "OBL-EUR-HOSTING", "op")
    q2 = treasury.create_quote(ctx, "OBL-EUR-HOSTING", "op")
    ctx.local_bank.next_conversion_fault = "timeout_after_accept"
    op = treasury.execute_conversion(ctx, q1["quote"]["id"], "op")
    assert op["status"] == "processing" and op["needs_reconciliation"] == 1
    with pytest.raises(treasury.TreasuryError, match="shortfall is now 0"):
        treasury.execute_conversion(ctx, q2["quote"]["id"], "op")
    with pytest.raises(treasury.TreasuryError, match="no shortfall"):
        treasury.create_quote(ctx, "OBL-EUR-HOSTING", "op")
    op = treasury.sync_conversion(ctx, op["id"])  # found by request_id
    assert op["status"] == "settled" and op["provider_id"]
    with ctx.conn() as conn:
        assert ledger.conservation(conn)["all_balanced"]


def test_concurrent_conversions_book_once(ctx):
    run_to(ctx, "agents")
    quotes = [treasury.create_quote(ctx, "OBL-EUR-HOSTING", "op")["quote"]["id"] for _ in range(4)]
    barrier = threading.Barrier(4)
    ok, errs = [], []

    def worker(qid):
        barrier.wait()
        try:
            ok.append(treasury.execute_conversion(ctx, qid, "op"))
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)

    threads = [threading.Thread(target=worker, args=(qid,)) for qid in quotes]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 1 and len(errs) == 3
    assert one(ctx, "SELECT COUNT(*) AS n FROM operations WHERE kind='fx_conversion' AND status != 'failed'")["n"] == 1


# 3. Immediate terminal transfer result keeps the wallet intact -------------------------------
@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_immediate_failed_refund_does_not_lose_cash(ctx, status, monkeypatch):
    run_to(ctx, "treasury")
    a = one(ctx, "SELECT * FROM approvals WHERE status='pending'")
    payouts.decide(ctx, a["id"], approve=True, actor="op", seen_scope_hash=a["scope_hash"])
    gbp_before = _cash(ctx, "GBP")["wallet_cash"]
    monkeypatch.setattr(ctx.local_bank, "create_transfer",
                        lambda **kw: TransferResult("tr_x", kw["request_id"], status, status.upper()))
    op = payouts.execute_refund(ctx, a["id"], "op")["operation"]
    gbp = _cash(ctx, "GBP")
    assert op["status"] == status
    assert gbp["wallet_cash"] == gbp_before == 1_370_000
    assert gbp["unapplied"] == 480_000 and gbp["balanced"]


# 4. Overpayment: evidence decides only the unapplied excess ----------------------------------
def _sign(ctx, cid, claim):
    return crypto.sign_claim(claim, ensure_keys(key_location(ctx.settings))[cid])


def _claim(ctx, dep, cid, inv, reason, amount, issued=None, expires=None):
    now = ctx.clock.now()
    return {"schema": "ledgerline.explain_payment.v1", "deposit_id": dep, "customer_id": cid, "currency": "USD",
            "amount_minor": amount, "invoice_id": inv, "reason": reason, "note": "n",
            "issued_at": iso(issued or now), "expires_at": iso(expires or now + timedelta(minutes=5)), "nonce": "x"}


def test_overpayment_evidence_credits_only_the_excess(ctx):
    # A deposit that pays an open invoice and overpays: allocate, then ask about the excess.
    body = webhooks.build_deposit_event("evt_acme", {"provider_ref": "SIM-DEP-2002", "currency": "USD",
                                                     "payer_name": "DUNMORE ANALYTICS LLC", "reference": "INV-2291",
                                                     "received_at": iso(ctx.clock.now())}, "1500.00")
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE invoices SET status='open' WHERE id='INV-2291'")
        conn.execute("INSERT INTO invoices(id, customer_id, currency, amount_minor, prior_paid_minor, status, issued_at, due_at, description) VALUES ('INV-2299','CUST-DUNMORE','USD',50000,0,'scheduled','2026-12-01T00:00:00Z','2026-12-31T00:00:00Z','April add-on')")
    ts = str(int(ctx.clock.now().timestamp() * 1000))
    s = ctx.settings.webhook_secret
    dep = webhooks.handle(ctx, raw_body=body, timestamp_ms=ts, signature=webhooks.sign(s, ts, body), secret=s, source="test")["deposit_id"]
    d = one(ctx, "SELECT * FROM deposits WHERE id = ?", (dep,))
    assert d["category"] == "overpayment" and d["status"] == "awaiting_evidence"
    env = _sign(ctx, "CUST-DUNMORE", _claim(ctx, dep, "CUST-DUNMORE", "INV-2299", "advance_payment", 150_000))
    with ctx.conn() as conn, db.transaction(conn):
        r = record_agent_answer(conn, ctx, dep, "CUST-DUNMORE", {"status": "answered", "envelope": env}, "test")
    assert r["verification"]["verdict"] == "verified"
    credit = one(ctx, "SELECT * FROM credits WHERE deposit_id = ?", (dep,))
    assert credit["amount_minor"] == 30_000  # 1,500 paid - 1,200 allocated
    with ctx.conn() as conn:
        assert ledger.conservation(conn)["all_balanced"]


def test_overpayment_evidence_too_large_for_invoice_escalates_not_500(ctx):
    body = webhooks.build_deposit_event("evt_acme2", {"provider_ref": "SIM-DEP-2003", "currency": "USD",
                                                      "payer_name": "ACME ROBOTICS INC", "reference": "INV-2240",
                                                      "received_at": iso(ctx.clock.now())}, "2600.00")
    ts = str(int(ctx.clock.now().timestamp() * 1000))
    s = ctx.settings.webhook_secret
    dep = webhooks.handle(ctx, raw_body=body, timestamp_ms=ts, signature=webhooks.sign(s, ts, body), secret=s, source="test")["deposit_id"]
    env = _sign(ctx, "CUST-ACME", {**_claim(ctx, dep, "CUST-ACME", "INV-2240", "invoice_payment", 260_000)})
    with ctx.conn() as conn, db.transaction(conn):
        r = record_agent_answer(conn, ctx, dep, "CUST-ACME", {"status": "answered", "envelope": env}, "test")
    assert r["plan"]["status"] == "escalated"
    assert one(ctx, "SELECT COUNT(*) AS n FROM allocations WHERE deposit_id = ?", (dep,))["n"] == 1


def test_answer_from_an_agent_we_did_not_ask_is_refused(ctx):
    run_to(ctx, "links")
    env = _sign(ctx, "CUST-FJORD", _claim(ctx, "DEP-1005", "CUST-FJORD", "INV-2291", "advance_payment", 120_000))
    with pytest.raises(ReconcileError, match="not the payer we asked"):
        with ctx.conn() as conn, db.transaction(conn):
            record_agent_answer(conn, ctx, "DEP-1005", "CUST-FJORD", {"status": "answered", "envelope": env}, "test")


# 5. Zero / negative signed validity interval --------------------------------------------------
@pytest.mark.parametrize("delta", [0, -60])
def test_non_positive_validity_interval_rejected(ctx, delta):
    run_to(ctx, "links")
    now = ctx.clock.now()
    claim = _claim(ctx, "DEP-1005", "CUST-DUNMORE", "INV-2291", "advance_payment", 120_000,
                   issued=now + timedelta(seconds=30), expires=now + timedelta(seconds=30 + delta))
    with ctx.conn() as conn:
        d = db.row(conn, "SELECT * FROM deposits WHERE id='DEP-1005'")
        v = verify(_sign(ctx, "CUST-DUNMORE", claim), deposit=d, asked_customer_id="CUST-DUNMORE", registry=key_registry(conn),
                   invoices=invoice_views(conn), now=now, max_ttl_seconds=900, skew_seconds=60)
    assert v.verdict == "rejected" and "validity interval" in v.reason


# 6. Exact money input -------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "-0.01", "1e3", " ", True, None, float("inf"), float("nan"), -5, "1,000.00"])
def test_to_minor_rejects_bad_input_with_money_error(bad):
    with pytest.raises(MoneyError):
        to_minor(bad, "USD")


def test_api_rejects_bad_amounts_without_500(client):
    client.post("/api/demo/step", json={"step": "seed"}, headers=OP)
    for amount in ["NaN", "Infinity", "-1", "abc", "1.001"]:
        r = client.post("/api/payments", json={"external_ref": f"x-{amount}", "currency": "USD", "amount": amount,
                                                "payer_name": "ACME ROBOTICS INC", "reference": "INV-2240"}, headers=OP)
        assert r.status_code == 422, (amount, r.status_code, r.text)
    for amount in [float("inf"), -1, 0.001]:
        body = webhooks.build_deposit_event("evt_bad_" + str(amount), {"provider_ref": f"bad-{amount}", "currency": "USD",
                                            "payer_name": "P", "reference": "", "received_at": "2026-10-27T00:00:00Z"}, "0")
        payload = json.loads(body)
        payload["data"]["amount"] = amount if amount != float("inf") else "Infinity"
        raw = json.dumps(payload).encode()
        ts = str(int(time.time() * 1000))
        r = client.post(client.webhook_url, content=raw,
                        headers={"x-timestamp": ts, "x-signature": webhooks.sign(client.webhook_secret, ts, raw)})
        assert r.status_code == 400, (amount, r.text)


# 7. Official webhook payload shape -----------------------------------------------------------
def _signed_post(client, payload):
    raw = json.dumps(payload).encode()
    ts = str(int(time.time() * 1000))
    return client.post(client.webhook_url, content=raw,
                       headers={"x-timestamp": ts, "x-signature": webhooks.sign(client.webhook_secret, ts, raw)})


def test_official_flat_settled_example_shape_is_ingested(client):
    # Shape from the Airwallex deposit.settled example (values swapped to a supported currency).
    payload = {"accountId": "acct_TOslkS7-MnyXlQuV8Lb4og", "id": "86b69f91-06f0-3fe8-8faf-4de58954ca8e", "name": "deposit.settled",
               "data": {"id": "67f687fe-dcf4-4462-92fa-20335301d9d8", "type": "DIRECT_DEBIT", "status": "SETTLED",
                        "created_at": "2017-03-20T14:00:01+1100", "currency": "USD", "amount": 12794.27,
                        "settled_at": "2017-03-22T14:00:00+0000", "funding_source_id": "fcfc369c", "reference": "5487287788",
                        "provider_transaction_id": "5487287788", "fee": {"currency": "USD", "amount": 12.79}}}
    r = _signed_post(client, payload)
    assert r.status_code == 200, r.text
    d = client.get(f"/api/deposits/{r.json()['deposit_id']}").json()
    assert d["amount_minor"] == 1_279_427 and d["received_at"] == "2017-03-22T14:00:00Z"
    assert d["payer_name"] == "UNKNOWN PAYER" and d["status"] == "escalated"  # no payer: never auto-matched


@pytest.mark.parametrize("data", [
    {"object": {"id": "x", "amount": 1, "currency": "USD", "status": "SETTLED"}},  # invented nested shape
    [], "str",
    {"id": "", "status": "SETTLED", "currency": "USD", "amount": 1, "settled_at": "2026-10-27T00:00:00Z"},
    {"id": "a", "status": "SETTLED", "currency": "USD", "amount": 1, "settled_at": "yesterday"},
    {"id": "a", "status": "SETTLED", "currency": "USD", "amount": 1, "settled_at": "2026-10-27T00:00:00Z", "payer": "ACME"},
    {"id": "a", "status": "SETTLED", "currency": ["USD"], "amount": 1, "settled_at": "2026-10-27T00:00:00Z"},
    {"id": "a", "status": "PENDING", "currency": "USD", "amount": 1, "settled_at": "2026-10-27T00:00:00Z"},
])
def test_malformed_deposit_data_is_controlled_400(client, data):
    r = _signed_post(client, {"id": "evt_m", "name": "deposit.settled", "data": data})
    assert r.status_code == 400, r.text


def test_sandbox_hint_supplies_payer_missing_from_settled_event(client):
    ctx = client.app.state.orgs.get(client.org_id)
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute("INSERT INTO deposit_hints VALUES ('awx-dep-1','ACME ROBOTICS INC','INV-2240','t')")
    payload = {"id": "evt_h", "name": "deposit.settled",
               "data": {"id": "awx-dep-1", "status": "SETTLED", "currency": "USD", "amount": 2000,
                        "settled_at": "2026-10-27T00:00:00+0000"}}
    r = _signed_post(client, payload).json()
    d = client.get(f"/api/deposits/{r['deposit_id']}").json()
    assert d["payer_name"] == "ACME ROBOTICS INC" and d["category"] == "clean_match"


# 8. LocalBank closes its connections ----------------------------------------------------------
def test_local_bank_releases_file_handles():
    tmp = tempfile.mkdtemp()
    bank = LocalBank(Path(tmp) / "bank.sqlite3", Clock())
    bank.create_transfer(request_id="r1", amount_minor=1, currency="USD", destination="d", reference="r")
    bank.find_transfer("r1")
    bank.reset()
    del bank
    # No gc.collect(): on Windows an unclosed sqlite connection would keep the file locked.
    (Path(tmp) / "bank.sqlite3").unlink()
    assert not (Path(tmp) / "bank.sqlite3").exists()
    gc.collect()


# 9. Pending FX proceeds are forecast cover, never spendable source cash ----------------------
def test_pending_fx_proceeds_cannot_fund_an_outbound_conversion(ctx):
    run_to(ctx, "agents")
    q1 = treasury.create_quote(ctx, "OBL-EUR-HOSTING", "op")
    ctx.local_bank.next_conversion_fault = "timeout_after_accept"
    treasury.execute_conversion(ctx, q1["quote"]["id"], "op")
    with ctx.conn() as conn:
        eur = treasury.wallet_position(conn, ctx)["EUR"]
    assert eur["fx_in_pending"] == 451_500
    assert eur["free_after_commitments"] == -451_500  # settled view still short
    assert eur["projected_after_pending_fx"] == 0  # forecast view: covered, no second conversion
    # A later small EUR receipt must not make pending EUR spendable for a GBP bill.
    ctx_dep = webhooks.build_deposit_event("evt_small", {"provider_ref": "SIM-DEP-3001", "currency": "EUR",
                                           "payer_name": "BRIGHTWAVE GMBH", "reference": "INV-2253",
                                           "received_at": iso(ctx.clock.now())}, "1750.00")
    ts = str(int(ctx.clock.now().timestamp() * 1000))
    s = ctx.settings.webhook_secret
    webhooks.handle(ctx, raw_body=ctx_dep, timestamp_ms=ts, signature=webhooks.sign(s, ts, ctx_dep), secret=s, source="test")
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE obligations SET amount_minor = 2000000, due_at = ? WHERE id = 'OBL-GBP-RENT'", (iso(ctx.clock.now() + timedelta(days=2)),))
        plan = treasury.plan_for_obligation(conn, ctx, "OBL-GBP-RENT")
    assert all(c["currency"] != "EUR" for c in plan["source_candidates"])


# 10. A missing lookup is not finality ---------------------------------------------------------
def test_missing_lookup_keeps_ambiguous_conversion_reserved(ctx):
    run_to(ctx, "agents")
    q1 = treasury.create_quote(ctx, "OBL-EUR-HOSTING", "op")
    ctx.local_bank.next_conversion_fault = "timeout_before_accept"
    op = treasury.execute_conversion(ctx, q1["quote"]["id"], "op")
    for _ in range(3):
        op = treasury.sync_conversion(ctx, op["id"])  # provider has nothing (yet)
        assert op["status"] == "processing" and op["needs_reconciliation"] == 1
    with ctx.conn() as conn:
        pos = treasury.wallet_position(conn, ctx)
        assert pos["USD"]["fx_out_reserved"] == q1["quote"]["sell_amount_minor"]
        assert treasury.plan_for_obligation(conn, ctx, "OBL-EUR-HOSTING")["deficit"] == 0
    with pytest.raises(treasury.TreasuryError, match="no shortfall"):
        treasury.create_quote(ctx, "OBL-EUR-HOSTING", "op")


def test_unexpected_provider_status_is_unknown_not_failure(ctx, monkeypatch):
    run_to(ctx, "agents")
    q1 = treasury.create_quote(ctx, "OBL-EUR-HOSTING", "op")
    from ledgerline.providers.base import ConversionResult

    monkeypatch.setattr(ctx.local_bank, "create_conversion", lambda **kw: ConversionResult("conv_odd", kw["request_id"], "weird_internal"))
    op = treasury.execute_conversion(ctx, q1["quote"]["id"], "op")
    assert op["status"] == "processing"
    with ctx.conn() as conn:
        assert treasury.wallet_position(conn, ctx)["USD"]["fx_out_reserved"] > 0
