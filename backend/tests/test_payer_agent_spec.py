"""docs/PAYER_AGENT_SPEC.md and its JSON schema say what the code does: same fields, a test vector that verifies, and
the reference agent's real answers fit the schema."""
import json
from datetime import timedelta
from pathlib import Path

import jsonschema
import pytest

from ledgerline import crypto, evidence
from ledgerline.clock import parse_iso
from ledgerline.context import DEFAULT_POLICY
from ledgerline.matching import InvoiceView
from ledgerline.payer_agents import remote
from ledgerline.payer_agents.client import QUESTION_FIELDS

from .test_remote_agent import _fresh_backoff, agent, evidence_for, loopback_app, practice_client, register  # noqa: F401

DOCS = Path(__file__).resolve().parents[2] / "docs"
SCHEMA = json.loads((DOCS / "schemas/explain_payment.v1.schema.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((DOCS / "schemas/explain_payment.v1.example.json").read_text(encoding="utf-8"))


def validator(name):
    return jsonschema.Draft202012Validator({**SCHEMA, "$ref": f"#/$defs/{name}"})


def test_the_schema_is_valid_and_lists_exactly_what_the_verifier_requires():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    claim = SCHEMA["$defs"]["claim"]
    assert set(claim["required"]) == set(claim["properties"]) == set(evidence._REQUIRED)
    assert set(claim["properties"]["reason"]["enum"]) == evidence.REASONS
    assert claim["properties"]["schema"]["const"] == evidence.CLAIM_SCHEMA == SCHEMA["$id"]
    question = SCHEMA["$defs"]["question"]
    assert set(question["required"]) == set(question["properties"]) == set(QUESTION_FIELDS)


def test_the_test_vector_fits_the_schema_and_verifies():
    validator("question").validate(EXAMPLE["question"])
    validator("answer").validate(EXAMPLE["answer"])
    env = EXAMPLE["answer"]["envelope"]
    assert crypto.canonical_json(env["claim"]).decode() == EXAMPLE["canonical"]
    assert env["key_id"] == crypto.key_id_for(EXAMPLE["public_key"])
    assert crypto.verify_signature(env["claim"], env["signature"], EXAMPLE["public_key"])
    # The same vector passes all three checks against books where the invoice is a scheduled one of that customer.
    claim = env["claim"]
    v = evidence.verify(env, deposit={"id": claim["deposit_id"], "currency": "USD", "amount_minor": 120_000},
                        asked_customer_id="CUST-DUNMORE",
                        registry={"CUST-DUNMORE": {"public_key": EXAMPLE["public_key"], "key_id": env["key_id"]}},
                        invoices={"INV-2291": InvoiceView("INV-2291", "CUST-DUNMORE", "USD", 120_000, 120_000, "scheduled", "2026-12-01")},
                        now=parse_iso(claim["issued_at"]) + timedelta(seconds=30),
                        max_ttl_seconds=DEFAULT_POLICY["evidence_max_ttl_seconds"],
                        skew_seconds=DEFAULT_POLICY["evidence_clock_skew_seconds"])
    assert v.verdict == "verified", v.reason


@pytest.mark.parametrize("change", [
    lambda c: c.update(extra="field"),
    lambda c: c.pop("nonce"),
    lambda c: c.update(amount_minor=1200.5),
    lambda c: c.update(reason="gift"),
])
def test_what_the_schema_refuses_the_verifier_refuses(change):
    env = json.loads(json.dumps(EXAMPLE["answer"]["envelope"]))
    change(env["claim"])
    assert not validator("envelope").is_valid(env)
    v = evidence.verify(env, deposit={"id": "DEP-1005", "currency": "USD", "amount_minor": 120_000}, asked_customer_id="CUST-DUNMORE",
                        registry={"CUST-DUNMORE": {"public_key": EXAMPLE["public_key"], "key_id": env["key_id"]}},
                        invoices={}, now=parse_iso("2026-11-03T10:15:30Z"), max_ttl_seconds=900, skew_seconds=60)
    assert v.verdict == "rejected"


def test_the_reference_agents_real_question_and_answer_fit_the_schema(loopback_app, agent, monkeypatch):  # noqa: F811
    c = practice_client(loopback_app)
    assert register(c, agent["url"], agent["public_key"]).status_code == 200
    sent = []
    real = remote.ask_remote

    def spy(url, reqs, *a, **k):
        sent.extend(reqs)
        return real(url, reqs, *a, **k)
    monkeypatch.setattr(remote, "ask_remote", spy)
    assert c.post("/api/deposits/DEP-1005/ask-agent").json()["verification"]["verdict"] == "verified"
    for q in sent:
        validator("question").validate(q)
    ev = evidence_for(c, "DEP-1005")[-1]
    validator("envelope").validate(ev["envelope"])
