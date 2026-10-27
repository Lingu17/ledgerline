"""Text people read says what happened, with money formatted as money (never raw minor units)."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from ledgerline.api.app import create_app
from ledgerline.config import load_settings
from ledgerline.workspace import _customer_slug

from .conftest import signup

RAW_MINOR = re.compile(r"(?<![\w.,-])\d{5,}(?![\w.,])")  # e.g. 175000 standing alone


def _client(tmp_path):
    app = create_app(load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path / "d"), "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
                                    "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": "", "ANTHROPIC_API_KEY": "",
                                    "LEDGERLINE_DATABASE_URL": ""}))
    c = TestClient(app)
    signup(c, email="text@deploy.test", start_with="sample")
    return c


def test_rejected_claim_reason_names_the_failed_check(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/deposits/DEP-1004/ask-agent").json()
    assert r["verification"]["verdict"] == "rejected"
    reason = c.get("/api/deposits/DEP-1004").json()["escalation_reason"]
    assert reason.startswith("Records check failed: ") and "belongs to another customer" in reason
    assert "Our records agree" not in reason


def test_operator_decision_and_ledger_checks_show_money(tmp_path):
    c = _client(tmp_path)
    c.post("/api/deposits/DEP-1004/ask-agent")
    r = c.post("/api/deposits/DEP-1004/resolve", json={"action": "credit", "amount": "1750.00", "note": "confirmed by phone"})
    assert r.status_code == 200, r.text
    plans = c.get("/api/deposits/DEP-1004").json()["plans"]
    summary = plans[-1]["plan"]["summary"] if "plan" in plans[-1] else plans[-1]["summary"]
    assert "EUR 1,750.00" in summary and not RAW_MINOR.search(summary), summary
    details = [ch["detail"] for v in c.get("/api/ledger").json()["conservation"]["currencies"].values() for ch in v["checks"]]
    assert all(not RAW_MINOR.search(d) for d in details), details
    assert any("USD " in d for d in details)


def test_customer_ids_drop_legal_suffixes_and_cut_at_word_boundaries():
    assert _customer_slug("Harbour Lane Ltd") == "HARBOURLANE"
    assert _customer_slug("Fjord Logistikk AS") == "FJORDLOGISTIKK"
    assert _customer_slug("A very long company name holdings") == "AVERYLONGCOMPANY"
    assert _customer_slug("Ltd") == "LTD"
    assert _customer_slug("!!") == "CUSTOMER"
