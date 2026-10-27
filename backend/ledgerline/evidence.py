"""The three checks applied to a payer agent's signed explain_payment answer.

A signed answer is a *claim*. Passing all three checks makes it usable evidence;
the action it leads to is still chosen and limited by code (see workflow.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from . import crypto
from .clock import parse_iso
from .matching import InvoiceView

CLAIM_SCHEMA = "ledgerline.explain_payment.v1"
REASONS = {"invoice_payment", "advance_payment", "duplicate_payment"}
_REQUIRED = {
    "schema": str,
    "deposit_id": str,
    "customer_id": str,
    "currency": str,
    "amount_minor": int,
    "invoice_id": str,
    "reason": str,
    "note": str,
    "issued_at": str,
    "expires_at": str,
    "nonce": str,
}


@dataclass
class Verification:
    checks: list[dict[str, Any]]
    verdict: str  # verified | rejected
    reason: str
    claim: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {"checks": self.checks, "verdict": self.verdict, "reason": self.reason, "claim": self.claim}


def _check(name: str, label: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "label": label, "passed": passed, "detail": detail}


# How a failed check reads in an escalation reason (the labels describe the check passing).
_FAILED = {"signature": "Signature check failed", "binding": "Freshness and binding check failed", "records": "Records check failed"}


def _structure_errors(envelope: Any) -> list[str]:
    if not isinstance(envelope, dict):
        return ["envelope is not an object"]
    errs = []
    for k in ("claim", "signature", "key_id"):
        if k not in envelope:
            errs.append(f"missing {k}")
    claim = envelope.get("claim")
    if not isinstance(claim, dict):
        return errs + ["claim is not an object"]
    for key, typ in _REQUIRED.items():
        v = claim.get(key)
        if isinstance(v, bool) or not isinstance(v, typ):
            errs.append(f"claim.{key} missing or not {typ.__name__}")
    extra = set(claim) - set(_REQUIRED)
    if extra:
        errs.append(f"unexpected claim fields: {sorted(extra)}")
    return errs


def verify(
    envelope: Any,
    *,
    deposit: dict[str, Any],
    asked_customer_id: str,
    registry: dict[str, dict[str, str]],
    invoices: dict[str, InvoiceView],
    now: datetime,
    max_ttl_seconds: int,
    skew_seconds: int,
    applicable_minor: int | None = None,
) -> Verification:
    """`applicable_minor` is the part of the deposit still unapplied (overpayments); defaults to the full amount."""
    errs = _structure_errors(envelope)
    if errs:
        checks = [
            _check("signature", "Signed by the registered customer key", False, "; ".join(errs)),
            _check("binding", "Names this exact deposit and is fresh", False, "not evaluated: malformed claim"),
            _check("records", "Our records agree", False, "not evaluated: malformed claim"),
        ]
        return Verification(checks, "rejected", "malformed answer: " + "; ".join(errs), None)

    claim: dict[str, Any] = envelope["claim"]

    # 1. Signature by the key the *asked* customer registered.
    reg = registry.get(asked_customer_id)
    if claim["customer_id"] != asked_customer_id:
        sig_ok, sig_detail = False, f"claim speaks for {claim['customer_id']} but we asked {asked_customer_id}"
    elif not reg or not reg.get("public_key"):
        sig_ok, sig_detail = False, f"no registered key for {asked_customer_id}"
    elif envelope.get("key_id") != reg["key_id"]:
        sig_ok, sig_detail = False, f"key_id {envelope.get('key_id')} is not the registered key {reg['key_id']}"
    elif not crypto.verify_signature(claim, str(envelope.get("signature", "")), reg["public_key"]):
        sig_ok, sig_detail = False, "Ed25519 signature does not verify over the canonical claim"
    else:
        sig_ok, sig_detail = True, f"Ed25519 signature valid for {reg['key_id']}"

    # 2. Bound to this deposit, unchanged amount/currency, fresh.
    problems = []
    if claim["schema"] != CLAIM_SCHEMA:
        problems.append(f"unknown schema {claim['schema']}")
    if claim["deposit_id"] != deposit["id"]:
        problems.append(f"names deposit {claim['deposit_id']}, not {deposit['id']}")
    if claim["currency"] != deposit["currency"]:
        problems.append(f"currency {claim['currency']} != deposit {deposit['currency']}")
    if claim["amount_minor"] != deposit["amount_minor"]:
        problems.append(f"amount {claim['amount_minor']} != deposit {deposit['amount_minor']}")
    try:
        issued, expires = parse_iso(claim["issued_at"]), parse_iso(claim["expires_at"])
        if issued > now + timedelta(seconds=skew_seconds):
            problems.append("issued in the future")
        if expires <= issued:
            problems.append("validity interval is zero or negative (expires_at must be after issued_at)")
        if expires <= now:
            problems.append(f"expired at {claim['expires_at']}")
        if expires - issued > timedelta(seconds=max_ttl_seconds):
            problems.append(f"validity window exceeds {max_ttl_seconds}s")
    except ValueError:
        problems.append("unparseable timestamps")
    bind_ok = not problems
    bind_detail = "matches deposit id, currency and amount; within validity window" if bind_ok else "; ".join(problems)

    # 3. Our own records agree with what the claim asserts.
    rec_problems = []
    applicable = deposit["amount_minor"] if applicable_minor is None else applicable_minor
    if applicable <= 0:
        rec_problems.append("nothing left unapplied on this deposit")
    inv = invoices.get(claim["invoice_id"])
    if claim["reason"] not in REASONS:
        rec_problems.append(f"unsupported reason {claim['reason']}")
    if inv is None:
        rec_problems.append(f"invoice {claim['invoice_id']} does not exist")
    else:
        if inv.customer_id != claim["customer_id"]:
            rec_problems.append(f"{inv.id} belongs to another customer ({inv.customer_id}), not {claim['customer_id']}")
        if inv.currency != deposit["currency"]:
            rec_problems.append(f"{inv.id} is billed in {inv.currency}")
        if not rec_problems and applicable > 0:
            if claim["reason"] == "invoice_payment":
                if inv.status != "open" or inv.remaining_minor < applicable:
                    rec_problems.append(f"{inv.id} has only {inv.remaining_minor} outstanding")
            elif claim["reason"] == "advance_payment":
                if inv.status not in ("scheduled", "open") or applicable > inv.remaining_minor:
                    rec_problems.append(f"advance exceeds {inv.id} remaining {inv.remaining_minor}")
            elif claim["reason"] == "duplicate_payment":
                if inv.remaining_minor != 0:
                    rec_problems.append(f"{inv.id} still has {inv.remaining_minor} outstanding; not a duplicate")
                elif applicable > inv.amount_minor:
                    rec_problems.append(f"claimed duplicate exceeds the {inv.id} amount")
    rec_ok = not rec_problems
    rec_detail = (
        f"{claim['invoice_id']} belongs to {claim['customer_id']}; {claim['reason']} fits the amount"
        if rec_ok
        else "; ".join(rec_problems)
    )

    checks = [
        _check("signature", "Signed by the registered customer key", sig_ok, sig_detail),
        _check("binding", "Names this exact deposit and is fresh", bind_ok, bind_detail),
        _check("records", "Our records agree", rec_ok, rec_detail),
    ]
    failed = [c for c in checks if not c["passed"]]
    if failed:
        return Verification(checks, "rejected", "; ".join(f"{_FAILED.get(c['name'], c['label'])}: {c['detail']}" for c in failed), claim)
    return Verification(checks, "verified", "all three checks passed", claim)
