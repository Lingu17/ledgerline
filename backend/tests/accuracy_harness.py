"""Randomized end-to-end accuracy harness.

Each seed builds a synthetic company and drives it through the real HTTP API, the same
calls the UI makes:
  - opening balances, customers (some with registered payer agents), invoices
  - credit notes, extra charges and voids
  - bank statement lines, typed in one at a time or imported as CSV (with bad rows mixed in)
  - repeated imports (idempotency) and operator resolution of escalated payments

Alongside, a reference model written from the product rules (not from the code) predicts
every result. After the scenario, each figure the API reports is compared to the model:
invoice balances and status, every deposit's category, status, payer and buckets,
import counts, wallet cash, credits and unapplied money, ledger conservation, and
that a different organization cannot read any of it.

Synthetic data only. Deterministic per seed: a failure can be replayed with the same seed.
"""
from __future__ import annotations

import base64
import csv
import io
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from fastapi.testclient import TestClient

CCYS = ("USD", "EUR", "GBP")
FEE_ABS = {"USD": 5_000, "EUR": 2_500, "GBP": 2_500}  # default policy: absolute fee tolerance (minor units)
FEE_BPS = 100  # ... and never more than 1% of what was billed
PASSWORD = "Accuracy-Run-2026-ok"

COMPANY_WORDS = ["Harbour", "Lumen", "Kestrel", "Orchard", "Basalt", "Meridian", "Copper", "Juniper", "Atlas", "Tidewater",
                 "Northwind", "Saffron", "Granite", "Willow", "Beacon", "Cobalt", "Fable", "Quarry", "Halcyon", "Ember"]
COMPANY_SUFFIX = [("Ltd", "GB"), ("GmbH", "DE"), ("Inc", "US"), ("BV", "NL"), ("SAS", "FR"), ("AB", "SE"), ("LLC", "US")]


class Mismatch(AssertionError):
    pass


def major(minor: int, style: int = 0) -> str:
    """Minor units -> decimal text the API accepts. Varies the formatting the way people type it."""
    whole, cents = divmod(minor, 100)
    if style == 1 and cents == 0:
        return str(whole)            # "1250"
    if style == 2 and cents % 10 == 0:
        return f"{whole}.{cents // 10}"  # "1250.5"
    return f"{whole}.{cents:02d}"     # "1250.50"


# --------------------------------------------------------------------------- reference model
@dataclass
class Inv:
    id: str
    cust: str
    ccy: str
    amount: int        # effective amount after adjustments
    remaining: int
    due: date
    void: bool = False
    touched: bool = False  # has an allocation or write-off (cannot be voided)


@dataclass
class Dep:
    id: str
    ccy: str
    amount: int
    cust: str | None
    category: str
    status: str
    allocated: int = 0
    credited: int = 0
    has_credit: bool = False

    @property
    def unapplied(self) -> int:
        return self.amount - self.allocated - self.credited


@dataclass
class Model:
    customers: dict[str, dict[str, Any]] = field(default_factory=dict)  # id -> {payers:set, agent:bool}
    invoices: dict[str, Inv] = field(default_factory=dict)
    deposits: dict[str, Dep] = field(default_factory=dict)
    opening: dict[str, int] = field(default_factory=dict)
    statement_refs: dict[str, tuple] = field(default_factory=dict)  # external_ref -> (ccy, amount, payer, reference) -> dep id
    ref_to_dep: dict[str, str] = field(default_factory=dict)

    def customer_for(self, payer: str) -> str | None:
        key = payer.strip().casefold()
        for cid, c in self.customers.items():
            if key in {p.casefold() for p in c["payers"]}:
                return cid
        return None

    def predict(self, dep_id: str, ccy: str, amount: int, payer: str, refs: list[str]) -> Dep:
        """The matching rules, as specified: never match on amount alone; payer and currency must agree."""
        cid = self.customer_for(payer)
        agent = bool(cid and self.customers[cid]["agent"])
        waiting = "awaiting_evidence" if agent else "escalated"
        d = Dep(dep_id, ccy, amount, cid, "", "")
        if not refs:
            d.category, d.status = "unknown_reference", waiting
            return d
        if cid is None:
            d.category, d.status = "unidentified_payer", "escalated"
            return d
        if any(r not in self.invoices for r in refs):
            d.category, d.status = "unknown_invoice", waiting
            return d
        invs = [self.invoices[r] for r in refs]
        if any(i.cust != cid for i in invs):
            d.category, d.status = "reference_conflict", "escalated"
            return d
        if any(i.ccy != ccy for i in invs):
            d.category, d.status = "wrong_currency", "escalated"
            return d
        payable = sorted((i for i in invs if not i.void and i.remaining > 0), key=lambda i: (i.due, i.id))
        total = sum(i.remaining for i in payable)
        if total == 0:
            d.category, d.status = "apparent_duplicate", waiting
            return d
        left = amount
        for inv in payable:
            take = min(inv.remaining, left)
            if take:
                inv.remaining -= take
                inv.touched = True
                d.allocated += take
                left -= take
        if amount == total:
            d.category, d.status = "clean_match", "matched"
        elif amount > total:
            d.category, d.status = "overpayment", waiting
        else:
            gap = total - amount
            if gap <= min(FEE_ABS[ccy], total * FEE_BPS // 10_000):
                for inv in reversed(payable):  # bank fee written off, latest-due invoice first
                    w = min(inv.remaining, gap)
                    if w:
                        inv.remaining -= w
                        inv.touched = True
                        gap -= w
                d.category, d.status = "clean_with_fee", "matched"
            else:
                d.category, d.status = "partial_payment", "partially_applied"
        return d

    def resolve(self, d: Dep, action: str, amount: int, invoice_id: str | None) -> None:
        if action == "allocate":
            inv = self.invoices[invoice_id]
            inv.remaining -= amount
            inv.touched = True
            d.allocated += amount
        else:
            d.credited += amount
            d.has_credit = True
        d.category = "operator_resolution"
        d.status = "escalated" if d.unapplied > 0 else ("matched" if d.allocated else "credited")


# --------------------------------------------------------------------------- scenario driver
class Scenario:
    def __init__(self, app, seed: int) -> None:
        self.rng = random.Random(seed)
        self.seed = seed
        self.c = TestClient(app)
        self.m = Model()
        self.today = date.today()
        self.log: list[str] = []
        self.stats: dict[str, int] = {}
        self.checks = 0
        email = f"acc-{seed}-{self.rng.randrange(10**8)}@accuracy.test"
        r = self.c.post("/api/auth/signup", json={"email": email, "name": "Accuracy Bot", "password": PASSWORD,
                                                   "organization_name": f"Accuracy {seed}", "start_with": "empty"})
        self.expect(r.status_code == 200, f"signup: {r.status_code} {r.text}")
        self.c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        self.org_id = r.json()["organization"]["id"]
        # This harness checks the rules against an independent model, so it predicts the state before any agent answer.
        # Asking by itself is covered in test_agent_loop.py.
        self.c.app.state.orgs.get(self.org_id).org["agent_auto_ask"] = False

    # -- helpers
    def expect(self, ok: bool, what: str) -> None:
        self.checks += 1
        if not ok:
            raise Mismatch(f"seed {self.seed}: {what}\nlast steps:\n  " + "\n  ".join(self.log[-8:]))

    def count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    def post(self, path: str, body: dict[str, Any], ok: bool = True) -> Any:
        r = self.c.post(f"/api{path}", json=body)
        if ok:
            self.expect(r.status_code == 200, f"POST {path} {body} -> {r.status_code} {r.text}")
            return r.json()
        return r

    # -- setup
    def setup(self) -> None:
        for ccy in self.rng.sample(CCYS, self.rng.randint(1, 3)):
            amt = self.rng.randrange(0, 5_000_000) * 100 // 100
            self.post("/treasury/opening-balance", {"currency": ccy, "amount": major(amt)})
            self.m.opening[ccy] = amt
            # A second opening balance for the same currency must be refused.
            self.expect(self.post("/treasury/opening-balance", {"currency": ccy, "amount": "1.00"}, ok=False).status_code == 422,
                        "second opening balance accepted")
        words = self.rng.sample(COMPANY_WORDS, self.rng.randint(3, 7))
        for w in words:
            suffix, country = self.rng.choice(COMPANY_SUFFIX)
            name = f"{w} {suffix}"
            payers = [f"{w.upper()} {suffix.upper()}"]
            if self.rng.random() < 0.4:
                payers.append(f"{w.upper()} TRADING")
            body = {"name": name, "country": country, "payer_names": payers, "refund_beneficiary": f"{name} - account (synthetic)"}
            agent = self.rng.random() < 0.35
            if agent:
                body["agent_key_id"] = f"key-{w.lower()}"
                body["agent_public_key"] = base64.b64encode(self.rng.randbytes(32)).decode()
            cust = self.post("/customers", body)
            self.m.customers[cust["id"]] = {"payers": set(payers), "agent": agent, "name": name}
        for _ in range(self.rng.randint(6, 30)):
            self.new_invoice()

    def new_invoice(self) -> None:
        cid = self.rng.choice(list(self.m.customers))
        ccy = self.rng.choice(CCYS)
        amount = self.rng.choice([self.rng.randrange(1_000, 200_000), self.rng.randrange(100_000, 5_000_000), self.rng.randrange(10_000, 50_000) * 100])
        due = self.today + timedelta(days=self.rng.randint(-20, 60))
        inv = self.post("/invoices", {"customer_id": cid, "currency": ccy, "amount": major(amount, self.rng.randint(0, 2)),
                                      "due_date": due.isoformat(), "description": f"Services {self.rng.randint(1, 999)}"})
        self.m.invoices[inv["id"]] = Inv(inv["id"], cid, ccy, amount, amount, due)
        self.log.append(f"invoice {inv['id']} {cid} {ccy} {amount} due {due}")
        self.count("invoices")

    # -- events
    def adjust(self) -> None:
        open_invs = [i for i in self.m.invoices.values() if not i.void]
        if not open_invs:
            return
        inv = self.rng.choice(open_invs)
        kind = self.rng.choice(["decrease", "increase", "void"])
        if kind == "void":
            r = self.post(f"/invoices/{inv.id}/adjustments", {"kind": "void", "reason": "Raised in error"}, ok=False)
            if inv.touched:
                self.expect(r.status_code == 422, f"void of paid {inv.id} accepted")
            else:
                self.expect(r.status_code == 200, f"void {inv.id}: {r.text}")
                inv.void, inv.amount, inv.remaining = True, 0, 0
                self.count("voids")
        elif kind == "decrease":
            if inv.remaining == 0:
                r = self.post(f"/invoices/{inv.id}/adjustments", {"kind": "decrease", "amount": "1.00", "reason": "Credit note"}, ok=False)
                self.expect(r.status_code == 422, f"decrease on settled {inv.id} accepted")
                return
            amt = self.rng.randint(1, inv.remaining)
            self.post(f"/invoices/{inv.id}/adjustments", {"kind": "decrease", "amount": major(amt), "reason": "Credit note"})
            inv.amount -= amt
            inv.remaining -= amt
            self.count("credit_notes")
        else:
            amt = self.rng.randint(100, 500_000)
            self.post(f"/invoices/{inv.id}/adjustments", {"kind": "increase", "amount": major(amt), "reason": "Extra hours"})
            inv.amount += amt
            inv.remaining += amt
            self.count("extra_charges")
        self.log.append(f"adjust {inv.id} {kind}")

    def reference_for(self, ids: list[str]) -> str:
        nums = [i.removeprefix("INV-") for i in ids]
        if len(nums) == 1:
            return self.rng.choice([f"INV-{nums[0]}", f"Invoice INV-{nums[0]}", f"inv {nums[0]}", f"Payment INV#{nums[0]} thanks",
                                    f"INV {nums[0]} PO 7781"])
        joiner = self.rng.choice([" + ", ", ", " & ", " and ", "/"])
        return self.rng.choice([f"INV {joiner.join(nums)}", "INV-" + joiner.join(f"INV-{n}" for n in nums)[4:],
                                "Invoices " + joiner.join(f"INV-{n}" for n in nums)])

    def make_payment(self) -> dict[str, Any] | None:
        """Pick a realistic statement line, and the invoice references it was written against."""
        m, rng = self.m, self.rng
        kind = rng.choices(["exact", "multi", "partial", "fee", "over", "duplicate", "noref", "stranger", "unknown_inv",
                            "foreign", "wrong_ccy", "void"],
                           weights=[16, 8, 10, 8, 7, 6, 6, 5, 4, 4, 4, 3])[0]
        custs = list(m.customers)
        cid = rng.choice(custs)
        payer = rng.choice(sorted(m.customers[cid]["payers"]))
        payer = rng.choice([payer, payer.lower(), payer.title(), f"  {payer} "])
        own = [i for i in m.invoices.values() if i.cust == cid]
        open_own = [i for i in own if not i.void and i.remaining > 0]
        refs: list[str] = []
        ccy = rng.choice(CCYS)
        if kind in ("exact", "partial", "fee", "over") and open_own:
            inv = rng.choice(open_own)
            refs, ccy = [inv.id], inv.ccy
            due = inv.remaining
            if kind == "exact":
                amount = due
            elif kind == "partial":
                amount = rng.randint(1, max(1, due - 1)) if due > 1 else due
            elif kind == "fee":
                # Boundaries matter most: exactly at the tolerance, one cent over, and well over.
                tol = min(FEE_ABS[ccy], due * FEE_BPS // 10_000)
                gap = rng.choice([rng.randint(0, tol), tol, tol + 1, 2 * tol, tol + 100])
                amount = max(1, due - gap)
            else:
                amount = due + rng.randint(1, 300_000)
        elif kind == "multi" and len([i for i in open_own if i.ccy == open_own[0].ccy]) >= 2:
            same = [i for i in open_own if i.ccy == open_own[0].ccy]
            picks = rng.sample(same, rng.randint(2, min(3, len(same))))
            refs, ccy = [i.id for i in picks], picks[0].ccy
            total = sum(i.remaining for i in picks)
            amount = rng.choice([total, max(1, total - rng.randint(1, max(1, total // 3))), total + rng.randint(1, 100_000)])
        elif kind == "duplicate" and [i for i in own if i.remaining == 0 and not i.void]:
            inv = rng.choice([i for i in own if i.remaining == 0 and not i.void])
            refs, ccy, amount = [inv.id], inv.ccy, max(inv.amount, 100)
        elif kind == "void" and [i for i in own if i.void]:
            inv = rng.choice([i for i in own if i.void])
            refs, ccy, amount = [inv.id], inv.ccy, rng.randint(100, 100_000)
        elif kind == "stranger":
            payer = rng.choice(["UNKNOWN TRADER LTD", "J SMITH", "PAYPAL *MARKETPL", "ZEPHYR HOLDINGS"])
            target = rng.choice(list(m.invoices.values()))
            refs, ccy, amount = ([target.id], target.ccy, target.remaining or 100) if rng.random() < 0.7 else ([], ccy, rng.randint(100, 900_000))
        elif kind == "unknown_inv":
            refs, amount = [f"INV-{rng.randint(9000, 9999)}"], rng.randint(100, 900_000)
        elif kind == "foreign" and len(custs) > 1:
            others = [i for i in m.invoices.values() if i.cust != cid]
            if not others:
                return None
            inv = rng.choice(others)
            refs, ccy, amount = [inv.id], inv.ccy, inv.remaining or 100
        elif kind == "wrong_ccy" and open_own:
            inv = rng.choice(open_own)
            refs, ccy, amount = [inv.id], rng.choice([c for c in CCYS if c != inv.ccy]), inv.remaining
        else:
            kind, refs, amount = "noref", [], rng.randint(100, 900_000)
            # The tempting shortcut: an unreferenced payment for exactly an open invoice's balance. Must not match.
            same = [i for i in m.invoices.values() if not i.void and i.remaining > 0]
            if same and rng.random() < 0.6:
                bait = rng.choice(same)
                ccy, amount = bait.ccy, bait.remaining
                if rng.random() < 0.5 and m.customers[bait.cust]["payers"]:
                    payer = sorted(m.customers[bait.cust]["payers"])[0]
                self.count("pay_noref_same_amount")
        reference = self.reference_for(refs) if refs else rng.choice(["", "Thank you", "Payment March", "Order 7788", "Remittance to follow"])
        self.count(f"pay_{kind}")
        return {"external_ref": f"STMT-{self.seed}-{len(m.statement_refs) + 1:04d}-{rng.randrange(10**6)}",
                "currency": ccy, "amount": major(amount, rng.randint(0, 2)), "payer_name": payer, "reference": reference,
                "_minor": amount, "_refs": refs}

    def _record_expected(self, p: dict[str, Any], dep_id: str) -> None:
        payer_upper = p["payer_name"].strip().upper()
        d = self.m.predict(dep_id, p["currency"], p["_minor"], payer_upper, p["_refs"])
        self.m.deposits[dep_id] = d
        self.m.statement_refs[p["external_ref"]] = (p["currency"], p["_minor"], payer_upper, p["reference"])
        self.m.ref_to_dep[p["external_ref"]] = dep_id
        self.log.append(f"pay {dep_id} {p['currency']} {p['_minor']} '{p['payer_name']}' ref='{p['reference']}' -> {d.category}")

    def pay_single(self) -> None:
        p = self.make_payment()
        if p is None:
            return
        body = {k: v for k, v in p.items() if not k.startswith("_")}
        if self.rng.random() < 0.3:
            body["received_at"] = (self.today - timedelta(days=self.rng.randint(0, 20))).isoformat()
        r = self.post("/payments", body)
        self.expect(r["created"] is True, f"payment not created: {r}")
        self._record_expected(p, r["deposit_id"])
        # Idempotency: same statement line again changes nothing; same reference with other details is refused.
        if self.rng.random() < 0.25:
            again = self.post("/payments", body)
            self.expect(again == {"deposit_id": r["deposit_id"], "created": False}, f"replay not idempotent: {again}")
            self.count("replays")
        if self.rng.random() < 0.1:
            bad = self.post("/payments", {**body, "amount": major(p["_minor"] + 1)}, ok=False)
            self.expect(bad.status_code == 409, f"conflicting replay accepted: {bad.status_code}")
            self.count("conflicting_replays")

    def pay_csv(self) -> None:
        rows, expect_created, expect_errors, expect_dupes = [], [], 0, 0
        for _ in range(self.rng.randint(2, 12)):
            p = self.make_payment()
            if p is None:
                continue
            rows.append(p)
            expect_created.append(p)
        # Mixed in: invalid lines that must be reported and change nothing.
        bad_lines = []
        for _ in range(self.rng.randint(0, 3)):
            ref = f"BAD-{self.seed}-{self.rng.randrange(10**8)}"
            bad_lines.append(self.rng.choice([
                {"external_ref": ref, "currency": "USD", "amount": "12,50", "payer_name": "X LTD", "reference": ""},
                {"external_ref": ref, "currency": "USD", "amount": "-5.00", "payer_name": "X LTD", "reference": ""},
                {"external_ref": ref, "currency": "GBP", "amount": "0.00", "payer_name": "X LTD", "reference": ""},
                {"external_ref": ref, "currency": "JPY", "amount": "100", "payer_name": "X LTD", "reference": ""},
                {"external_ref": ref, "currency": "EUR", "amount": "10.001", "payer_name": "X LTD", "reference": ""},
                {"external_ref": "has space", "currency": "EUR", "amount": "10.00", "payer_name": "X LTD", "reference": ""},
                {"external_ref": ref, "currency": "EUR", "amount": "10.00", "payer_name": "X", "reference": ""},
                {"external_ref": ref, "currency": "EUR", "amount": "10.00", "payer_name": "X LTD", "reference": "",
                 "received_at": (self.today + timedelta(days=3)).isoformat()},
            ]))
        expect_errors += len(bad_lines)
        # And some lines already imported earlier (duplicates of the same statement line).
        replay = []
        if self.m.statement_refs and self.rng.random() < 0.5:
            for ref in self.rng.sample(list(self.m.statement_refs), min(len(self.m.statement_refs), self.rng.randint(1, 3))):
                ccy, amt, payer, reference = self.m.statement_refs[ref]
                replay.append({"external_ref": ref, "currency": ccy, "amount": major(amt), "payer_name": payer, "reference": reference})
            expect_dupes = len(replay)
        lines = [{k: v for k, v in p.items() if not k.startswith("_")} for p in rows] + bad_lines + replay
        order = list(range(len(lines)))
        self.rng.shuffle(order)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["external_ref", "received_at", "currency", "amount", "payer_name", "reference"], lineterminator="\n")
        w.writeheader()
        for i in order:
            w.writerow({"received_at": "", **lines[i]})
        r = self.post("/payments/import", {"csv": buf.getvalue()})
        self.expect((r["created"], r["duplicates"], r["errors"]) == (len(expect_created), expect_dupes, expect_errors),
                    f"import counts {r['created']}/{r['duplicates']}/{r['errors']} expected {len(expect_created)}/{expect_dupes}/{expect_errors}: "
                    + str([x for x in r["results"] if x["status"] == "error"]))
        by_ref = {x["external_ref"]: x for x in r["results"]}
        # Lines are processed in file order, which matters when two lines touch the same invoice.
        for i in order:
            if i < len(rows):
                p = rows[i]
                self._record_expected(p, by_ref[p["external_ref"]]["deposit_id"])
        for line in replay:
            self.expect(by_ref[line["external_ref"]]["deposit_id"] == self.m.ref_to_dep[line["external_ref"]], "replay mapped to a new deposit")
        self.count("csv_imports")

    def resolve_one(self) -> None:
        esc = [d for d in self.m.deposits.values() if d.status == "escalated" and d.unapplied > 0]
        if not esc:
            return
        d = self.rng.choice(esc)
        cid = d.cust
        body: dict[str, Any] = {"note": "Confirmed with customer by phone"}
        if cid is None:
            cid = self.rng.choice(list(self.m.customers))
            body["customer_id"] = cid
        targets = [i for i in self.m.invoices.values() if i.cust == cid and i.ccy == d.ccy and not i.void and i.remaining > 0]
        if targets and self.rng.random() < 0.7:
            inv = self.rng.choice(targets)
            amt = self.rng.randint(1, min(inv.remaining, d.unapplied))
            # Over-allocation must be refused before the valid one.
            if inv.remaining < d.unapplied:
                r = self.post(f"/deposits/{d.id}/resolve", {**body, "action": "allocate", "invoice_id": inv.id, "amount": major(inv.remaining + 1)}, ok=False)
                self.expect(r.status_code == 422, f"over-allocation accepted on {inv.id}: {r.status_code}")
            self.post(f"/deposits/{d.id}/resolve", {**body, "action": "allocate", "invoice_id": inv.id, "amount": major(amt)})
            if d.cust is None:
                d.cust = cid
            self.m.resolve(d, "allocate", amt, inv.id)
            self.count("resolve_allocate")
        elif not d.has_credit:
            amt = self.rng.choice([d.unapplied, self.rng.randint(1, d.unapplied)])
            self.post(f"/deposits/{d.id}/resolve", {**body, "action": "credit", "amount": major(amt)})
            if d.cust is None:
                d.cust = cid
            self.m.resolve(d, "credit", amt, None)
            self.count("resolve_credit")
        else:
            return
        # Another customer's invoice is never a valid target.
        foreign = [i for i in self.m.invoices.values() if i.cust != (d.cust or cid) and i.ccy == d.ccy and i.remaining > 0 and not i.void]
        if foreign and d.status == "escalated":
            r = self.post(f"/deposits/{d.id}/resolve", {"note": "wrong", "action": "allocate", "invoice_id": foreign[0].id, "amount": "0.01"}, ok=False)
            self.expect(r.status_code == 422, f"allocation to another customer's invoice accepted: {r.status_code}")
        self.log.append(f"resolve {d.id} -> {d.status} alloc={d.allocated} credit={d.credited}")

    def run(self) -> None:
        self.setup()
        for _ in range(self.rng.randint(15, 45)):
            op = self.rng.choices(["single", "csv", "adjust", "resolve", "invoice"], weights=[45, 12, 12, 14, 8])[0]
            {"single": self.pay_single, "csv": self.pay_csv, "adjust": self.adjust, "resolve": self.resolve_one,
             "invoice": self.new_invoice}[op]()
        self.verify()

    # -- verification against the API
    def verify(self) -> None:
        m = self.m
        invoices = self.c.get("/api/invoices", params={"limit": 500}).json()
        got = {i["id"]: i for i in invoices}
        self.expect(set(got) == set(m.invoices), f"invoice ids differ: {set(got) ^ set(m.invoices)}")
        for iid, inv in m.invoices.items():
            g = got[iid]
            exp_status = "void" if inv.void else "open"
            self.expect((g["remaining_minor"], g["effective_amount_minor"], g["effective_status"]) == (inv.remaining, inv.amount, exp_status),
                        f"{iid}: API remaining/amount/status {g['remaining_minor']}/{g['effective_amount_minor']}/{g['effective_status']} "
                        f"expected {inv.remaining}/{inv.amount}/{exp_status}")
        r = self.c.get("/api/deposits", params={"limit": 500})
        self.expect(int(r.headers.get("x-total-count", -1)) == len(m.deposits), f"deposit count {r.headers.get('x-total-count')} != {len(m.deposits)}")
        for did, d in m.deposits.items():
            g = self.c.get(f"/api/deposits/{did}").json()
            b = g["buckets"]
            actual = (g["category"], g["status"], g.get("customer_id"), b["allocated"], b["credited"], b["unapplied"], g["amount_minor"], g["currency"])
            expected = (d.category, d.status, d.cust, d.allocated, d.credited, d.unapplied, d.amount, d.ccy)
            self.expect(actual == expected, f"{did}: API {actual} expected {expected}")
            self.expect(g["source"] == "manual_import", f"{did}: source {g['source']}")
        tr = self.c.get("/api/treasury").json()
        wallets = {w["currency"]: w for w in tr["wallets"]}
        for ccy in CCYS:
            deps = [d for d in m.deposits.values() if d.ccy == ccy]
            cash = m.opening.get(ccy, 0) + sum(d.amount for d in deps)
            w = wallets[ccy]
            exp = (cash, sum(d.credited for d in deps), sum(d.unapplied for d in deps))
            got_w = (w["cash"], w["customer_credits"], w["unapplied_held"])
            self.expect(got_w == exp, f"{ccy} wallet cash/credits/unapplied {got_w} expected {exp}")
        led = self.c.get("/api/ledger").json()
        failed = [(ccy, c["name"], c["detail"]) for ccy, v in led["conservation"]["currencies"].items() for c in v["checks"] if not c["passed"]]
        self.expect(led["conservation"]["all_balanced"] and not failed, f"ledger checks failed: {failed}")
        for p in led["per_deposit"] if isinstance(led["per_deposit"], list) else []:
            self.expect(p.get("balanced", True), f"per-deposit check failed: {p}")
        audit_n = int(self.c.get("/api/audit", params={"q": "deposit.received", "limit": 1}).headers["x-total-count"])
        self.expect(audit_n == len(m.deposits), f"audit has {audit_n} deposit.received events for {len(m.deposits)} deposits")

    def isolation_check(self, other: "Scenario") -> None:
        """Another organization's session sees none of this organization's records."""
        for did in list(self.m.deposits)[:5]:
            self.expect(other.c.get(f"/api/deposits/{did}").status_code == 404, f"{other.org_id} can read {did}")
        theirs = {i["id"] for i in other.c.get("/api/invoices", params={"limit": 500}).json()}
        self.expect(theirs == set(other.m.invoices), "invoice list leaked across organizations")


def run_sample_walkthrough(app, n: int) -> dict[str, Any]:
    """The six-deposit sample company, end to end through every walkthrough step (MCP agents, FX, approval, refund)."""
    c = TestClient(app)
    r = c.post("/api/auth/signup", json={"email": f"walk-{n}-{random.randrange(10**8)}@accuracy.test", "name": "Walk",
                                          "password": PASSWORD, "organization_name": f"Walk {n}", "start_with": "sample"})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    for step in ["seed", "deposits", "links", "agents", "treasury", "approve", "bank_sent", "bank_paid"]:
        if step == "approve":
            # A person approves the over-limit refund, confirming the exact scope they saw.
            for a in c.get("/api/approvals").json():
                if a["status"] == "pending":
                    ok = c.post(f"/api/approvals/{a['id']}/approve", json={"scope_hash": a["scope_hash"]})
                    assert ok.status_code == 200, f"walkthrough {n} approve: {ok.status_code} {ok.text}"
        s = c.post("/api/demo/step", json={"step": step})
        assert s.status_code == 200, f"walkthrough {n} step {step}: {s.status_code} {s.text}"
    score = c.get("/api/overview").json()["scorecard"]
    deps = {d["id"]: (d["category"], d["status"], d["buckets"]["allocated"], d["buckets"]["unapplied"])
            for d in c.get("/api/deposits", params={"limit": 50}).json()}
    return {"score": score, "deposits": deps}
