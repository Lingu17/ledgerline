"""Deterministic first-pass matching rules. Pure functions: no I/O, no model calls.

A deposit is only matched when the reference names invoices that belong to
the identified payer *and* share the deposit currency. Amount alone never
selects an invoice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .money import fmt

_INV_BLOCK = re.compile(
    r"\bINV(?:OICE)?[\s\-#:.]*(\d{3,6})((?:\s*(?:\+|&|,|/|\band\b)\s*(?:INV(?:OICE)?[\s\-#:.]*)?\d{3,6}\b)*)",
    re.IGNORECASE,
)
_NUM = re.compile(r"\d{3,6}")


def parse_invoice_refs(reference: str) -> list[str]:
    """'INV 2231 + 2240' -> ['INV-2231', 'INV-2240']. Order preserved, duplicates removed."""
    found: list[str] = []
    for m in _INV_BLOCK.finditer(reference or ""):
        numbers = [m.group(1)] + _NUM.findall(m.group(2) or "")
        for n in numbers:
            inv = f"INV-{n}"
            if inv not in found:
                found.append(inv)
    return found


@dataclass
class InvoiceView:
    id: str
    customer_id: str
    currency: str
    amount_minor: int
    remaining_minor: int
    status: str
    due_at: str


@dataclass
class Plan:
    category: str
    summary: str
    customer_id: str | None
    actions: list[dict[str, Any]] = field(default_factory=list)
    needs_evidence: bool = False
    needs_human: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "summary": self.summary,
            "customer_id": self.customer_id,
            "actions": self.actions,
            "needs_evidence": self.needs_evidence,
            "needs_human": self.needs_human,
            "notes": self.notes,
        }


def identify_customer(payer_name: str, customers: list[dict[str, Any]]) -> dict[str, Any] | None:
    key = (payer_name or "").strip().casefold()
    for c in customers:
        if key and key in {n.casefold() for n in c["payer_names"]}:
            return c
    return None


def initial_plan(
    deposit: dict[str, Any],
    customers: list[dict[str, Any]],
    invoices: dict[str, InvoiceView],
    fee_tolerance_minor: int,
    fee_tolerance_bps: int | None = None,
) -> Plan:
    amount = deposit["amount_minor"]
    ccy = deposit["currency"]
    customer = identify_customer(deposit["payer_name"], customers)
    cid = customer["id"] if customer else None
    has_agent = bool(customer and customer.get("agent_public_key"))
    refs = parse_invoice_refs(deposit.get("reference", ""))

    def ask_agent(question: str) -> dict[str, Any]:
        if has_agent:
            return {"type": "ask_payer_agent", "customer_id": cid, "question": question}
        return {"type": "escalate", "reason": "no registered payer agent; route remittance text to evidence reader / operator"}

    if not refs:
        same_amount = sorted(
            i.id for i in invoices.values() if i.currency == ccy and i.remaining_minor == amount and i.status == "open"
        )
        plan = Plan(
            category="unknown_reference",
            summary=("No invoice reference on the deposit. Ask the payer's agent; never match on amount alone." if has_agent else
                     "No invoice reference and no registered payer agent: a person decides (remittance text can be read as "
                     "evidence); never match on amount alone."),
            customer_id=cid,
            actions=[ask_agent(f"Which invoice is the {ccy} deposit {deposit['id']} for?"),
                     {"type": "hold_unapplied", "amount_minor": amount}],
            needs_evidence=has_agent,
            needs_human=not has_agent,
        )
        if same_amount:
            plan.notes.append(
                "Open invoices with the same amount exist (" + ", ".join(same_amount) + "); not used for matching."
            )
        return plan

    if customer is None:
        return Plan(
            category="unidentified_payer",
            summary=f"Payer '{deposit['payer_name']}' is not a registered customer; reference alone is not enough.",
            customer_id=None,
            actions=[{"type": "escalate", "reason": "unidentified payer"}, {"type": "hold_unapplied", "amount_minor": amount}],
            needs_human=True,
        )

    missing = [r for r in refs if r not in invoices]
    if missing:
        return Plan(
            category="unknown_invoice",
            summary=f"Reference names invoice(s) we do not have: {', '.join(missing)}.",
            customer_id=cid,
            actions=[ask_agent(f"Deposit references {', '.join(missing)} which we cannot find."),
                     {"type": "hold_unapplied", "amount_minor": amount}],
            needs_evidence=has_agent,
            needs_human=not has_agent,
        )

    referenced = [invoices[r] for r in refs]
    foreign = [i.id for i in referenced if i.customer_id != cid]
    if foreign:
        return Plan(
            category="reference_conflict",
            summary=f"Reference names invoice(s) owned by another customer: {', '.join(foreign)}.",
            customer_id=cid,
            actions=[{"type": "escalate", "reason": "reference names another customer's invoice"},
                     {"type": "hold_unapplied", "amount_minor": amount}],
            needs_human=True,
        )

    wrong_ccy = [i.id for i in referenced if i.currency != ccy]
    if wrong_ccy:
        return Plan(
            category="wrong_currency",
            summary=f"Paid in {ccy} but {', '.join(wrong_ccy)} is billed in {referenced[0].currency}. Held; no implied FX.",
            customer_id=cid,
            actions=[{"type": "escalate", "reason": "currency mismatch between deposit and invoice"},
                     {"type": "hold_unapplied", "amount_minor": amount}],
            needs_human=True,
        )

    scheduled = [i.id for i in referenced if i.status == "scheduled"]
    payable = sorted((i for i in referenced if i.status == "open" and i.remaining_minor > 0), key=lambda i: (i.due_at, i.id))
    total_remaining = sum(i.remaining_minor for i in payable)

    if total_remaining == 0:
        reason = "references a not-yet-issued invoice" if scheduled else "every referenced invoice is already settled"
        return Plan(
            category="apparent_duplicate",
            summary=(f"Looks like a duplicate: {reason}. Proposed refund held until the payer's agent explains." if has_agent else
                     f"Looks like a duplicate: {reason}. No registered payer agent, so a person decides before any refund."),
            customer_id=cid,
            actions=[ask_agent(f"Deposit {deposit['id']} references {', '.join(refs)}, which {reason}."),
                     {"type": "propose_refund", "amount_minor": amount, "status": "awaiting_evidence"}],
            needs_evidence=has_agent,
            needs_human=not has_agent,
        )

    actions: list[dict[str, Any]] = []
    left = amount
    for inv in payable:
        take = min(inv.remaining_minor, left)
        if take > 0:
            actions.append({"type": "allocate", "invoice_id": inv.id, "amount_minor": take})
            left -= take

    if amount == total_remaining:
        return Plan("clean_match", f"Exact match to {', '.join(i.id for i in payable)}.", cid, actions)

    if amount > total_remaining:
        actions.append({"type": "hold_unapplied", "amount_minor": left})
        actions.insert(0, ask_agent(f"Deposit exceeds {', '.join(refs)} by {fmt(left, ccy)}. What is the excess for?"))
        return Plan(
            "overpayment",
            "Referenced invoices settled; the excess is held unapplied pending the payer's explanation.",
            cid,
            actions,
            needs_evidence=has_agent,
            needs_human=not has_agent,
        )

    shortfall = total_remaining - amount
    # A bank fee is small in absolute terms AND relative to what was billed (970 of 1,000 is not a fee).
    tolerance = fee_tolerance_minor
    if fee_tolerance_bps is not None:
        tolerance = min(tolerance, total_remaining * fee_tolerance_bps // 10_000)
    if shortfall <= tolerance:
        # Write off the gap on the invoice(s) left short, latest-due last.
        gap = shortfall
        for inv in reversed(payable):
            allocated = next((a["amount_minor"] for a in actions if a["invoice_id"] == inv.id), 0)
            short_here = min(inv.remaining_minor - allocated, gap)
            if short_here > 0:
                actions.append({"type": "write_off_fee", "invoice_id": inv.id, "amount_minor": short_here})
                gap -= short_here
        return Plan(
            "clean_with_fee",
            f"Short by {fmt(shortfall, ccy)}, within the {fmt(tolerance, ccy)} bank-fee tolerance; gap written off.",
            cid,
            actions,
        )

    for inv in payable:
        allocated = next((a["amount_minor"] for a in actions if a["invoice_id"] == inv.id), 0)
        if inv.remaining_minor - allocated > 0:
            actions.append({"type": "payment_link", "invoice_id": inv.id, "amount_minor": inv.remaining_minor - allocated})
    return Plan(
        "partial_payment",
        f"Short by {fmt(shortfall, ccy)}, above the {fmt(tolerance, ccy)} fee tolerance. Partial allocation and a payment link for the exact balance.",
        cid,
        actions,
    )
