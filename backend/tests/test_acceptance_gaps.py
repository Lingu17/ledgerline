"""Acceptance-matrix gaps: exact boundaries, currency-bound claims, races between ingestion paths and between
operators, and upload size limits."""
from __future__ import annotations

import base64
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from ledgerline import claude_reader, db, sandbox_receipts as receipts, workspace
from ledgerline.matching import initial_plan
from ledgerline.reconcile import deposit_buckets, ingest_deposit
from ledgerline.webhooks import _parse_deposit

from .conftest import run_to, signup
from .test_evidence import _by_name, _claim, _sign, _verify, awaiting  # noqa: F401  (fixture re-export)
from .test_judge_safety import _app
from .test_matching import CUSTOMERS, dep, inv


# --------------------------------------------------------------------------- fee tolerance boundary
def test_fee_tolerance_boundary_is_inclusive_and_one_cent_more_is_partial():
    invoices = {"INV-7100": inv("INV-7100", amount=100_000)}
    at_limit = initial_plan(dep(95_000, "INV-7100"), CUSTOMERS, invoices, 5_000)
    over = initial_plan(dep(94_999, "INV-7100"), CUSTOMERS, invoices, 5_000)
    assert at_limit.category == "clean_with_fee"
    assert sum(a["amount_minor"] for a in at_limit.actions if a["type"] == "write_off_fee") == 5_000
    assert over.category == "partial_payment"
    assert not any(a["type"] == "write_off_fee" for a in over.actions)


# --------------------------------------------------------------------------- signed claim in the wrong currency
def test_validly_signed_claim_in_another_currency_fails_binding(awaiting):  # noqa: F811
    env = _sign(awaiting, "CUST-DUNMORE", _claim(awaiting, "DEP-1005", "CUST-DUNMORE", "INV-2291", "advance_payment", ccy="EUR"))
    v = _verify(awaiting, "DEP-1005", "CUST-DUNMORE", env)
    assert _by_name(v)["signature"] is True and _by_name(v)["binding"] is False and v.verdict == "rejected"


# --------------------------------------------------------------------------- webhook vs polling race
def _settled(id_):
    return {"id": id_, "status": "SETTLED", "amount": 7.5, "currency": "EUR", "global_account_id": "ga_eur",
            "created_at": "2026-10-29T15:00:00+0000", "settled_at": "2026-10-29T15:00:01+0000",
            "payer": {"name": "Race Payer"}, "reference": "race"}


def test_webhook_and_discovery_racing_for_one_deposit_book_it_once(ctx):
    ctx.sandbox = SimpleNamespace(list_deposits=lambda page_num, page_size=100: {"items": [_settled("race-1")], "has_more": False})
    ctx.settings.airwallex_global_account_ids = {"EUR": "ga_eur"}
    start = threading.Barrier(6)
    errors = []

    def webhook():
        start.wait()
        with ctx.conn() as conn, db.transaction(conn):
            ingest_deposit(conn, ctx, _parse_deposit({"data": _settled("race-1")}), source="airwallex_sandbox_webhook",
                           global_account_id="ga_eur")

    def poll():
        start.wait()
        receipts.discover(ctx, "owner", since="2026-10-29T00:00:00Z")

    def guarded(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - any failure is a test failure, reported below
            errors.append(repr(exc))

    threads = [threading.Thread(target=guarded, args=(fn,)) for fn in (webhook, poll) * 3]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    with ctx.conn() as conn:
        rows = db.rows(conn, "SELECT id, amount_minor FROM deposits WHERE provider_ref = 'race-1'")
        assert len(rows) == 1 and rows[0]["amount_minor"] == 750
        assert db.row(conn, "SELECT COUNT(*) AS n FROM journal_entries WHERE memo LIKE ?", (f"%{rows[0]['id']}%",))["n"] >= 1


# --------------------------------------------------------------------------- two operators resolving one payment
def test_two_operators_resolving_the_same_payment_cannot_over_apply(ctx):
    run_to(ctx, "agents")  # DEP-1004 is escalated with EUR 1,750 unapplied
    with ctx.conn() as conn:
        d = db.row(conn, "SELECT * FROM deposits WHERE id = 'DEP-1004'")
    assert d["status"] == "escalated"
    start = threading.Barrier(4)
    ok, refused = [], []

    def resolve(i):
        start.wait()
        try:
            workspace.resolve_deposit(ctx, "DEP-1004", {"action": "credit", "amount": "1750.00", "customer_id": "CUST-FJORD",
                                                         "note": f"operator {i} confirmed by phone"}, f"op{i}@test")
            ok.append(i)
        except Exception as exc:  # noqa: BLE001 - the losers must get a controlled refusal
            refused.append(type(exc).__name__)

    threads = [threading.Thread(target=resolve, args=(i,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 1 and len(refused) == 3
    with ctx.conn() as conn:
        b = deposit_buckets(conn, "DEP-1004")
        credited = db.row(conn, "SELECT COALESCE(SUM(amount_minor), 0) AS n FROM credits WHERE deposit_id = 'DEP-1004'")["n"]
    assert credited == 175_000 and b["unapplied"] == 0


# --------------------------------------------------------------------------- upload limits
def test_pdf_over_the_size_limit_is_refused_before_any_model_call(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_reader, "_claude_read", lambda *a: (_ for _ in ()).throw(AssertionError("must not call Claude")))
    c = TestClient(_app(tmp_path, ANTHROPIC_API_KEY="sk-test-not-real"))
    signup(c, email="big@deploy.test", start_with="sample")
    big = b"%PDF-1.4\n" + b"0" * claude_reader.PDF_MAX_BYTES
    r = c.post("/api/deposits/DEP-1004/read-remittance", json={"pdf_base64": base64.b64encode(big).decode()})
    assert r.status_code == 409 and "3 MB" in r.json()["detail"]
    with_body = c.post("/api/deposits/DEP-1004/read-remittance", json={"pdf_base64": "A" * 4_400_000})
    assert with_body.status_code == 422  # beyond the request field limit: refused by validation, never decoded


def test_claude_token_usage_is_recorded_per_call_and_kept_out_of_evidence(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setattr(claude_reader, "_claude_read", lambda ctx, text: {
        "tool": "escalate", "input": {"reason": "no invoice named"}, "model": "claude-opus-5-5",
        "usage": {"input_tokens": 812, "output_tokens": 95}})
    app = _app(tmp_path, ANTHROPIC_API_KEY="sk-test-not-real")
    c = TestClient(app)
    signup(c, email="usage@deploy.test", start_with="sample")
    r = c.post("/api/deposits/DEP-1004/read-remittance", json={"text": "Payment for services, thanks"})
    assert r.status_code == 200 and "usage" not in r.json()["proposal"]
    with app.state.control.conn() as conn:
        row = db.row(conn, "SELECT status, detail FROM claude_calls ORDER BY id DESC LIMIT 1")
    assert row["status"] == "succeeded" and _json.loads(row["detail"]) == {"input_tokens": 812, "output_tokens": 95}


def test_payer_signing_keys_are_owner_only_and_old_files_are_repaired(tmp_path):
    import os

    import pytest

    from ledgerline.payer_agents.keys import ensure_keys, keys_path, load_keys

    if os.name != "posix":
        pytest.skip("file modes are POSIX-only; checked on Linux CI and the VM")
    keys = ensure_keys(tmp_path)
    path = keys_path(tmp_path)
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)  # a file written by an older version
    assert load_keys(tmp_path) == keys and path.stat().st_mode & 0o777 == 0o600
