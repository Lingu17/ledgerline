"""Synthetic demo scenario. All names, accounts and amounts are fictional.

Dates are offsets from the demo clock at the moment of reset, so the
"EUR bill due in 3 days" stays 3 days away whenever the demo is run.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from . import audit, db
from .clock import iso
from .payer_agents.keys import public_registry

DEMO_TABLES = (
    "deposit_conversions", "invoice_adjustments", "early_pay_offers", "plan_runs", "bill_payments", "treasury_decisions", "operation_events", "operations", "approvals", "evidence", "plans", "payment_links", "credits",
    "writeoffs", "allocations", "fx_quotes", "deposits", "invoices", "obligations", "customers",
    "wallet_opening", "deposit_hints", "journal_lines", "journal_entries", "webhook_events", "audit_events",
)

CUSTOMERS = [
    ("CUST-ACME", "Acme Robotics Inc", "US", ["ACME ROBOTICS INC"], "Acme Robotics Inc - US local account (synthetic)"),
    ("CUST-BRIGHTWAVE", "Brightwave GmbH", "DE", ["BRIGHTWAVE GMBH"], "Brightwave GmbH - SEPA account (synthetic)"),
    ("CUST-CALDER", "Calder & Finch Ltd", "GB", ["CALDER AND FINCH LTD", "CALDER & FINCH LTD"], "Calder & Finch Ltd - UK account (synthetic)"),
    ("CUST-DUNMORE", "Dunmore Analytics LLC", "US", ["DUNMORE ANALYTICS LLC"], "Dunmore Analytics LLC - US account (synthetic)"),
    ("CUST-EASTGATE", "Eastgate Media Ltd", "GB", ["EASTGATE MEDIA LTD"], "Eastgate Media Ltd - UK account (synthetic)"),
    ("CUST-FJORD", "Fjord Logistikk AS", "NO", ["FJORD LOGISTIKK AS"], "Fjord Logistikk AS - SEPA account (synthetic)"),
]

# id, customer, ccy, amount_minor, prior_paid_minor, status, issued_offset_days, due_offset_days, description
INVOICES = [
    ("INV-2231", "CUST-ACME", "USD", 300_000, 0, "open", -32, -2, "Platform licence, Q3 seats"),
    ("INV-2238", "CUST-EASTGATE", "GBP", 480_000, 480_000, "paid", -45, -15, "Annual analytics retainer (settled last month)"),
    ("INV-2240", "CUST-ACME", "USD", 200_000, 0, "open", -25, 5, "Implementation services, October"),
    ("INV-2244", "CUST-DUNMORE", "USD", 120_000, 120_000, "paid", -40, -10, "February platform subscription (settled)"),
    ("INV-2252", "CUST-BRIGHTWAVE", "EUR", 500_000, 0, "open", -31, -1, "Data pipeline build, milestone 2"),
    ("INV-2253", "CUST-BRIGHTWAVE", "EUR", 175_000, 0, "open", -18, 12, "Support plan, Q4"),
    ("INV-2260", "CUST-CALDER", "GBP", 360_000, 0, "open", -33, -3, "Custom reporting module"),
    ("INV-2291", "CUST-DUNMORE", "USD", 120_000, 0, "scheduled", 4, 34, "March platform subscription (scheduled, not yet issued)"),
]

# The six deposits: provider_ref, ccy, amount_minor, payer_name, reference, received_offset_hours
DEPOSITS = [
    ("SIM-DEP-1001", "USD", 500_000, "ACME ROBOTICS INC", "INV 2231 + 2240", -20),
    ("SIM-DEP-1002", "EUR", 498_500, "BRIGHTWAVE GMBH", "Invoice INV-2252", -18),
    ("SIM-DEP-1003", "GBP", 240_000, "CALDER AND FINCH LTD", "INV-2260 part payment", -15),
    ("SIM-DEP-1004", "EUR", 175_000, "FJORD LOGISTIKK AS", "", -12),
    ("SIM-DEP-1005", "USD", 120_000, "DUNMORE ANALYTICS LLC", "INV-2244", -9),
    ("SIM-DEP-1006", "GBP", 480_000, "EASTGATE MEDIA LTD", "INV-2238", -6),
]

# Messy remittance documents an evidence reader (Claude or the offline fixture) can read.
REMITTANCE_DOCS: dict[str, str] = {
    "SIM-DEP-1004": (
        "From: ap@fjord-logistikk.example\nSubject: payment\n\n"
        "Hei! we sent EUR 1.750,00 this week. this is for the Brightwave support invoice inv 2253, "
        "we are settling it for them as part of our reseller arrangement (no PO). "
        "Pls confirm receipt. -- Ingrid, Fjord AP"
    ),
    "SIM-DEP-1005": (
        "From: finance@dunmore.example\nSubject: Remittance advice\n\n"
        "USD 1,200.00 - prepayment for March subscription per PO 7781. Template ref INV-2244 reused by mistake."
    ),
}

OPENING_BALANCES = {"USD": 1_800_000, "EUR": 150_000, "GBP": 650_000}

# id, payee, ccy, amount_minor, due_offset_days, description
OBLIGATIONS = [
    ("OBL-EUR-HOSTING", "Kestrel Cloud GmbH", "EUR", 900_000, 3, "Hosting and EU data residency, monthly invoice"),
    ("OBL-USD-PAYROLL", "US contractor payroll", "USD", 600_000, 9, "Contractor payroll run"),
    ("OBL-GBP-RENT", "Shoreditch Workspace Ltd", "GBP", 200_000, 24, "London desk rental, quarterly"),
]


def reset_demo(conn: sqlite3.Connection, data_dir, now: datetime) -> None:
    """Delete demo-only rows and seed the scenario. Policy and the pause switch are kept."""
    registry = public_registry(data_dir)
    with db.transaction(conn):
        for table in DEMO_TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('journal_entries','journal_lines','audit_events','plans','allocations','writeoffs','credits','operation_events')")
        db.set_setting(conn, "demo_epoch", iso(now))
        for cid, name, country, payers, dest in CUSTOMERS:
            reg = registry.get(cid, {})
            conn.execute(
                "INSERT INTO customers(id, name, country, payer_names, agent_key_id, agent_public_key, refund_beneficiary, demo_only) VALUES (?,?,?,?,?,?,?,1)",
                (cid, name, country, json.dumps(payers), reg.get("key_id"), reg.get("public_key"), dest),
            )
        for inv_id, cid, ccy, amt, prior, status, issued, due, desc in INVOICES:
            conn.execute(
                "INSERT INTO invoices(id, customer_id, currency, amount_minor, prior_paid_minor, status, issued_at, due_at, description) VALUES (?,?,?,?,?,?,?,?,?)",
                (inv_id, cid, ccy, amt, prior, status, iso(now + timedelta(days=issued)), iso(now + timedelta(days=due)), desc),
            )
            if status == "open":
                audit.post(conn, iso(now), f"Invoice {inv_id} issued", "invoice", inv_id,
                           audit.move("accounts_receivable", "revenue", ccy, amt))
        for ccy, amt in OPENING_BALANCES.items():
            conn.execute("INSERT INTO wallet_opening VALUES (?,?)", (ccy, amt))
            audit.post(conn, iso(now), f"Opening {ccy} wallet balance", "opening", ccy,
                       audit.move(f"cash:{ccy}", "opening_equity", ccy, amt))
        for oid, payee, ccy, amt, due, desc in OBLIGATIONS:
            conn.execute(
                "INSERT INTO obligations(id, payee, currency, amount_minor, due_at, description, status) VALUES (?,?,?,?,?,?, 'scheduled')",
                (oid, payee, ccy, amt, iso(now + timedelta(days=due)), desc),
            )
        audit.record(conn, iso(now), "system", "demo.reset", "demo", "scenario",
                     {"customers": len(CUSTOMERS), "invoices": len(INVOICES), "obligations": len(OBLIGATIONS)})


def scenario_deposit_payloads(now: datetime) -> list[dict[str, Any]]:
    out = []
    for ref, ccy, amt, payer, reference, hours in DEPOSITS:
        out.append({
            "provider_ref": ref,
            "currency": ccy,
            "amount_minor": amt,
            "payer_name": payer,
            "reference": reference,
            "received_at": iso(now + timedelta(hours=hours)),
        })
    return out
