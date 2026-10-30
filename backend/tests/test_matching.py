from ledgerline.matching import InvoiceView, initial_plan, parse_invoice_refs
from ledgerline.money import MoneyError, convert_ceil, to_minor

import pytest
from decimal import Decimal

CUSTOMERS = [
    {"id": "C1", "payer_names": ["ACME"], "agent_public_key": "k"},
    {"id": "C2", "payer_names": ["OTHER"], "agent_public_key": "k"},
    {"id": "C3", "payer_names": ["NOAGENT"], "agent_public_key": None},
]


def inv(id_, cust="C1", ccy="USD", amount=100_000, remaining=None, status="open", due="2026-11-01T00:00:00Z"):
    return InvoiceView(id_, cust, ccy, amount, amount if remaining is None else remaining, status, due)


INVOICES = {
    "INV-2231": inv("INV-2231", amount=300_000, due="2026-10-25T00:00:00Z"),
    "INV-2240": inv("INV-2240", amount=200_000, due="2026-11-01T00:00:00Z"),
    "INV-3000": inv("INV-3000", cust="C2", amount=150_000),
    "INV-4000": inv("INV-4000", ccy="EUR", amount=100_000),
    "INV-5000": inv("INV-5000", amount=100_000, remaining=0, status="paid"),
}


def dep(amount, ref, payer="ACME", ccy="USD"):
    return {"id": "D", "amount_minor": amount, "currency": ccy, "reference": ref, "payer_name": payer}


@pytest.mark.parametrize("ref,expected", [
    ("INV 2231 + 2240", ["INV-2231", "INV-2240"]),
    ("Invoice INV-2252", ["INV-2252"]),
    ("inv#2231, inv 2240 and 2241", ["INV-2231", "INV-2240", "INV-2241"]),
    ("paid 21 Oct 2026", []),
    ("", []),
])
def test_parse_refs(ref, expected):
    assert parse_invoice_refs(ref) == expected


def test_split_reference_exact_match_allocates_both():
    p = initial_plan(dep(500_000, "INV 2231 + 2240"), CUSTOMERS, INVOICES, 5_000)
    assert p.category == "clean_match"
    assert [(a["invoice_id"], a["amount_minor"]) for a in p.actions] == [("INV-2231", 300_000), ("INV-2240", 200_000)]


def test_fee_within_tolerance_writes_off_gap():
    p = initial_plan(dep(497_000, "INV 2231 + 2240"), CUSTOMERS, INVOICES, 5_000)
    assert p.category == "clean_with_fee"
    allocated = sum(a["amount_minor"] for a in p.actions if a["type"] == "allocate")
    written = sum(a["amount_minor"] for a in p.actions if a["type"] == "write_off_fee")
    assert allocated == 497_000 and written == 3_000


def test_short_beyond_tolerance_is_partial_with_exact_link():
    p = initial_plan(dep(250_000, "INV-2231"), CUSTOMERS, INVOICES, 5_000)
    assert p.category == "partial_payment"
    link = next(a for a in p.actions if a["type"] == "payment_link")
    assert link == {"type": "payment_link", "invoice_id": "INV-2231", "amount_minor": 50_000}


def test_no_reference_never_matches_on_amount_alone():
    p = initial_plan(dep(150_000, ""), CUSTOMERS, {**INVOICES, "INV-9": inv("INV-9", amount=150_000)}, 5_000)
    assert p.category == "unknown_reference"
    assert not any(a["type"] == "allocate" for a in p.actions)
    assert "INV-9" in p.notes[0] and "not used" in p.notes[0]


def test_reference_to_other_customers_invoice_is_escalated():
    p = initial_plan(dep(150_000, "INV-3000"), CUSTOMERS, INVOICES, 5_000)
    assert p.category == "reference_conflict" and p.needs_human
    assert not any(a["type"] == "allocate" for a in p.actions)


def test_wrong_currency_held_without_fx():
    p = initial_plan(dep(100_000, "INV-4000", ccy="USD"), CUSTOMERS, INVOICES, 5_000)
    assert p.category == "wrong_currency"
    assert not any(a["type"] == "allocate" for a in p.actions)


def test_paid_invoice_reference_is_apparent_duplicate_pending_evidence():
    p = initial_plan(dep(100_000, "INV-5000"), CUSTOMERS, INVOICES, 5_000)
    assert p.category == "apparent_duplicate" and p.needs_evidence
    assert {"type": "propose_refund", "amount_minor": 100_000, "status": "awaiting_evidence"} in p.actions


def test_overpayment_allocates_remaining_and_holds_excess():
    p = initial_plan(dep(350_000, "INV-2231"), CUSTOMERS, INVOICES, 5_000)
    assert p.category == "overpayment"
    assert {"type": "allocate", "invoice_id": "INV-2231", "amount_minor": 300_000} in p.actions
    assert {"type": "hold_unapplied", "amount_minor": 50_000} in p.actions


def test_unknown_payer_without_agent_escalates():
    p = initial_plan(dep(100_000, "", payer="NOAGENT"), CUSTOMERS, INVOICES, 5_000)
    assert p.needs_human and not p.needs_evidence


def test_money_conversion_is_exact():
    assert to_minor("4970.10", "USD") == 497_010
    assert to_minor(4970.1, "USD") == 497_010
    with pytest.raises(MoneyError):
        to_minor("1.001", "USD")
    with pytest.raises(MoneyError):
        to_minor("10", "JPY")
    # 4515.00 EUR at 0.92 EUR/USD needs USD 4907.61 (rounded up, never short)
    assert convert_ceil(451_500, "USD", "EUR", Decimal("0.92")) == 490_761


def test_970_of_1000_is_partial_not_a_fee():
    invoices = {"INV-7001": inv("INV-7001", amount=100_000)}
    p = initial_plan(dep(97_000, "INV-7001"), CUSTOMERS, invoices, 5_000, 100)
    assert p.category == "partial_payment"
    assert {"type": "allocate", "invoice_id": "INV-7001", "amount_minor": 97_000} in p.actions
    assert {"type": "payment_link", "invoice_id": "INV-7001", "amount_minor": 3_000} in p.actions


def test_small_fee_on_large_invoice_is_written_off_with_relative_cap():
    invoices = {"INV-7001": inv("INV-7001", amount=500_000)}
    p = initial_plan(dep(497_000, "INV-7001"), CUSTOMERS, invoices, 5_000, 100)
    assert p.category == "clean_with_fee"


def test_plan_text_matches_its_action_when_the_payer_has_no_agent():
    # Seen live on 30 Oct: the summary said "Ask the payer's agent" while the action escalated to a person.
    p = initial_plan(dep(50_000, "", payer="NOAGENT"), CUSTOMERS, INVOICES, 5_000)
    assert p.actions[0]["type"] == "escalate" and "Ask the payer's agent" not in p.summary and "a person decides" in p.summary
    with_agent = initial_plan(dep(50_000, ""), CUSTOMERS, INVOICES, 5_000)
    assert with_agent.actions[0]["type"] == "ask_payer_agent" and "Ask the payer's agent" in with_agent.summary
    dup = initial_plan(dep(100_000, "INV-5000", payer="NOAGENT"), CUSTOMERS, {**INVOICES, "INV-5000": inv("INV-5000", cust="C3", amount=100_000, remaining=0, status="paid")}, 5_000)
    assert dup.category == "apparent_duplicate" and "a person decides" in dup.summary
