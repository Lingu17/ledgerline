"""Each simulated customer's own accounts-payable records.

The agent answers from *its* books. Fjord's agent is deliberately wrong: it
claims an invoice that belongs to Brightwave, to exercise check 3.
"""
from __future__ import annotations

from typing import Any

BOOKS: dict[str, list[dict[str, Any]]] = {
    "CUST-DUNMORE": [
        {
            "currency": "USD",
            "amount_minor": 120_000,
            "invoice_id": "INV-2291",
            "reason": "advance_payment",
            "note": "Advance for the March platform subscription (our PO 7781). Not a repeat of INV-2244; "
            "our remittance template reused the old reference.",
        }
    ],
    "CUST-EASTGATE": [
        {
            "currency": "GBP",
            "amount_minor": 480_000,
            "invoice_id": "INV-2238",
            "reason": "duplicate_payment",
            "note": "Our AP batch re-ran and paid INV-2238 a second time in error. Please refund to our account.",
        }
    ],
    "CUST-FJORD": [
        {
            "currency": "EUR",
            "amount_minor": 175_000,
            "invoice_id": "INV-2253",
            "reason": "invoice_payment",
            "note": "Payment for INV-2253.",
        }
    ],
}


def lookup(customer_id: str, currency: str, amount_minor: int) -> dict[str, Any] | None:
    for entry in BOOKS.get(customer_id, []):
        if entry["currency"] == currency and entry["amount_minor"] == amount_minor:
            return entry
    return None
