"""Proposal capabilities: deposit discovery fallback, beneficiary creation, current FX rates and PDF remittance."""
from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ledgerline import beneficiaries, claude_reader, db, sandbox_receipts as receipts

from .conftest import signup
from .test_judge_safety import _app


# --------------------------------------------------------------------------- deposit discovery
def _dep(id_, **kw):
    d = {"id": id_, "status": "SETTLED", "amount": 12.5, "currency": "EUR", "global_account_id": "ga_eur",
         "created_at": "2026-10-29T15:00:00+0000", "settled_at": "2026-10-29T15:00:01+0000",
         "payer": {"name": "Discovered Payer"}, "reference": "no invoice"}
    d.update(kw)
    return d


def _discover_ctx(ctx, pages):
    calls = []

    def list_deposits(page_num, page_size=100):
        calls.append(page_num)
        return pages[page_num]

    ctx.sandbox = SimpleNamespace(list_deposits=list_deposits)
    ctx.settings.airwallex_global_account_ids = {"EUR": "ga_eur"}
    return calls


def test_discovery_ingests_only_own_settled_deposits_since_cutoff(ctx):
    items = [
        _dep("mine-1"),
        _dep("mine-old", created_at="2026-10-28T10:00:00+0000"),
        _dep("other-account", global_account_id="ga_someone_else"),
        _dep("pending", status="PENDING"),
        _dep("wrong-ccy", currency="GBP"),
        _dep("bad-amount", amount="abc"),
    ]
    calls = _discover_ctx(ctx, [{"items": items[:3], "has_more": True}, {"items": items[3:], "has_more": False}])
    out = receipts.discover(ctx, "owner", since="2026-10-29T14:00:00Z")
    assert calls == [0, 1]
    assert out["seen"] == 6 and len(out["ingested"]) == 1
    assert (out["before_cutoff"], out["other_account"], out["not_settled"], out["rejected"]) == (1, 1, 1, 2)
    with ctx.conn() as conn:
        row = db.row(conn, "SELECT * FROM deposits WHERE provider_ref = 'mine-1'")
        assert row["source"] == "airwallex_sandbox_poll" and row["amount_minor"] == 1250 and row["global_account_id"] == "ga_eur"
        assert db.row(conn, "SELECT COUNT(*) AS n FROM deposits WHERE provider_ref <> 'mine-1' AND source = 'airwallex_sandbox_poll'")["n"] == 0
    # Running again books nothing new: the provider id is the idempotency key.
    _discover_ctx(ctx, [{"items": items, "has_more": False}])
    again = receipts.discover(ctx, "owner", since="2026-10-29T14:00:00Z")
    assert again["ingested"] == [] and again["already_known"] == 1


def test_discovery_does_not_duplicate_a_webhook_delivered_deposit(ctx):
    from ledgerline.reconcile import ingest_deposit
    from ledgerline.webhooks import _parse_deposit

    with ctx.conn() as conn, db.transaction(conn):
        ingest_deposit(conn, ctx, _parse_deposit({"data": _dep("hooked")}), source="airwallex_sandbox_webhook", global_account_id="ga_eur")
    _discover_ctx(ctx, [{"items": [_dep("hooked")], "has_more": False}])
    out = receipts.discover(ctx, "owner", since="2026-10-29T00:00:00Z")
    assert out["ingested"] == [] and out["already_known"] == 1
    with ctx.conn() as conn:
        assert db.row(conn, "SELECT COUNT(*) AS n FROM deposits WHERE provider_ref = 'hooked'")["n"] == 1


def test_discovery_needs_a_configured_account(ctx):
    _discover_ctx(ctx, [{"items": [], "has_more": False}])
    ctx.settings.airwallex_global_account_ids = {}
    with pytest.raises(receipts.SandboxReceiptError):
        receipts.discover(ctx, "owner", since="2026-10-29T00:00:00Z")


# --------------------------------------------------------------------------- beneficiaries
FORM = {"company_name": "Acme Retail GmbH", "bank_name": "Test Bank", "street_address": "1 Teststrasse", "city": "Berlin",
        "postcode": "10115", "iban": "DE89 3704 0044 0532 0130 00"}


def test_beneficiary_body_is_built_field_by_field():
    body = beneficiaries.build_body("EUR_DE_LOCAL", FORM)
    bank = body["beneficiary"]["bank_details"]
    assert bank == {"account_currency": "EUR", "bank_country_code": "DE", "account_name": "Acme Retail GmbH",
                    "bank_name": "Test Bank", "iban": "DE89370400440532013000"}
    assert body["transfer_methods"] == ["LOCAL"] and body["beneficiary"]["entity_type"] == "COMPANY"
    gb = beneficiaries.build_body("GBP_GB_LOCAL", {**FORM, "account_number": "12345678", "sort_code": "40-47-84"})
    assert gb["beneficiary"]["bank_details"]["account_routing_type1"] == "sort_code"
    assert gb["beneficiary"]["bank_details"]["account_routing_value1"] == "404784"


@pytest.mark.parametrize("corridor,change", [
    ("EUR_DE_LOCAL", {"iban": "not-an-iban"}),
    ("EUR_DE_LOCAL", {"company_name": "<script>"}),
    ("EUR_DE_LOCAL", {"postcode": ""}),
    ("GBP_GB_LOCAL", {"account_number": "123", "sort_code": "404784"}),
    ("USD_US_LOCAL", {"account_number": "123456789", "aba": "12"}),
    ("XXX", {}),
])
def test_beneficiary_input_is_refused_before_any_provider_call(corridor, change):
    with pytest.raises(beneficiaries.BeneficiaryError):
        beneficiaries.build_body(corridor, {**FORM, **change})


def _bene_ctx(ctx, errors=()):
    calls = []
    ctx.sandbox = SimpleNamespace(
        validate_beneficiary=lambda body: calls.append(("validate", body)) or list(errors),
        create_beneficiary=lambda body: calls.append(("create", body)) or {"id": "ben-123", **body},
    )
    return calls


def test_beneficiary_is_validated_then_created_and_linked_to_the_customer(ctx):
    calls = _bene_ctx(ctx)
    out = beneficiaries.create(ctx, "EUR_DE_LOCAL", FORM, "owner@test", customer_id="CUST-ACME")
    assert [c[0] for c in calls] == ["validate", "create"]
    assert out["id"] == "ben-123" and out["account"] == "…3000" and "DE8937" not in str(out)
    with ctx.conn() as conn:
        assert db.row(conn, "SELECT refund_beneficiary FROM customers WHERE id = 'CUST-ACME'")["refund_beneficiary"] == "ben-123"
        a = db.row(conn, "SELECT * FROM audit_events WHERE action = 'beneficiary.created'")
        assert a and "DE89370400440532013000" not in a["detail"]


def test_provider_validation_errors_stop_creation(ctx):
    calls = _bene_ctx(ctx, errors=[{"field": "beneficiary.bank_details.iban", "code": "083"}])
    with pytest.raises(beneficiaries.BeneficiaryError, match="bank_details.iban"):
        beneficiaries.create(ctx, "EUR_DE_LOCAL", FORM, "owner@test")
    assert [c[0] for c in calls] == ["validate"]


def test_beneficiary_for_unknown_customer_is_refused_before_creation(ctx):
    calls = _bene_ctx(ctx)
    with pytest.raises(beneficiaries.BeneficiaryError):
        beneficiaries.create(ctx, "EUR_DE_LOCAL", FORM, "owner@test", customer_id="CUST-NOPE")
    assert calls == []


def test_sandbox_tools_are_reserved_for_the_allowlisted_owner(tmp_path):
    app = _app(tmp_path, AIRWALLEX_CLIENT_ID="cid-test", AIRWALLEX_API_KEY="key-test")
    c = TestClient(app)
    signup(c, email="judge@deploy.test", start_with="sample")
    assert c.post("/api/integrations/sandbox/deposits/discover").status_code == 403
    assert c.get("/api/integrations/sandbox/beneficiaries").status_code == 403
    assert c.get("/api/integrations/sandbox/beneficiaries/schema", params={"corridor": "EUR_DE_LOCAL"}).status_code == 403
    assert c.post("/api/integrations/sandbox/beneficiaries", json={"corridor": "EUR_DE_LOCAL", **FORM}).status_code == 403


# --------------------------------------------------------------------------- rates
def test_local_workspace_rates_are_labelled_synthetic(tmp_path):
    c = TestClient(_app(tmp_path))
    signup(c, email="rates@deploy.test", start_with="sample")
    r = c.get("/api/treasury/rates").json()
    assert r["source"] == "synthetic" and "synthetic" in r["label"].lower() and len(r["rates"]) == 6


def test_airwallex_rate_parsing():
    from ledgerline.providers.airwallex import AirwallexSandbox

    a = AirwallexSandbox.__new__(AirwallexSandbox)
    a._request = lambda *_a, **_k: {"rate": 0.826797, "created_at": "2026-10-29T15:21:59+0000"}
    assert a.current_rate("EUR", "GBP") == {"sell": "EUR", "buy": "GBP", "rate": "0.826797", "as_of": "2026-10-29T15:21:59+0000"}
    a._request = lambda *_a, **_k: {"rate": True}
    from ledgerline.providers.base import ProviderError
    with pytest.raises(ProviderError):
        a.current_rate("EUR", "GBP")


# --------------------------------------------------------------------------- PDF remittance
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def test_pdf_needs_claude_and_is_never_guessed_offline(tmp_path):
    c = TestClient(_app(tmp_path))
    signup(c, email="pdf@deploy.test", start_with="sample")
    r = c.post("/api/deposits/DEP-1004/read-remittance", json={"pdf_base64": base64.b64encode(PDF).decode()})
    assert r.status_code == 409 and "needs the Claude API" in r.json()["detail"]


def test_pdf_is_sent_to_claude_as_a_document_and_stored_as_a_hash(tmp_path, monkeypatch):
    seen = []

    def fake(ctx, text, pdf=None):
        seen.append(pdf)
        return {"tool": "escalate", "input": {"reason": "pdf read"}, "model": "fake-model"}

    monkeypatch.setattr(claude_reader, "_claude_read", fake)
    c = TestClient(_app(tmp_path, ANTHROPIC_API_KEY="sk-test-not-real"))
    signup(c, email="pdf2@deploy.test", start_with="sample")
    r = c.post("/api/deposits/DEP-1004/read-remittance", json={"pdf_base64": base64.b64encode(PDF).decode()})
    assert r.status_code == 200 and seen == [PDF]
    assert r.json()["proposal"]["tool"] == "escalate" and r.json()["source"] == "claude_extracted"
    ev = [e for d in c.get("/api/evidence").json() for e in d["evidence"] if e["id"] == r.json()["evidence_id"]]
    stored = str(ev[0])
    assert len(ev) == 1 and "sha256" in stored and base64.b64encode(PDF).decode() not in stored


@pytest.mark.parametrize("body,status", [
    ({"pdf_base64": base64.b64encode(b"not a pdf").decode()}, 409),
    ({"pdf_base64": "!!!"}, 422),
    ({"pdf_base64": base64.b64encode(PDF).decode(), "text": "both at once"}, 422),
])
def test_bad_pdf_uploads_are_refused(tmp_path, monkeypatch, body, status):
    monkeypatch.setattr(claude_reader, "_claude_read", lambda *a: pytest.fail("Claude must not be called"))
    c = TestClient(_app(tmp_path, ANTHROPIC_API_KEY="sk-test-not-real"))
    signup(c, email="pdf3@deploy.test", start_with="sample")
    assert c.post("/api/deposits/DEP-1004/read-remittance", json=body).status_code == status
