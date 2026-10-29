"""Sandbox refund beneficiaries: schema lookup, validation and creation (owner, allowlisted organization only).

Only three LOCAL corridors are offered, each mapped field by field to the Airwallex request, so the API never
forwards arbitrary JSON. Every body is checked by POST /beneficiaries/validate before POST /beneficiaries/create.
"""
from __future__ import annotations

import re
from typing import Any

from . import audit, db
from .clock import iso
from .providers.base import ProviderError

CORRIDORS: dict[str, dict[str, Any]] = {
    "EUR_DE_LOCAL": {"currency": "EUR", "country": "DE", "label": "EUR · Germany · SEPA (IBAN)",
                     "fields": {"iban": r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$"}},
    "GBP_GB_LOCAL": {"currency": "GBP", "country": "GB", "label": "GBP · United Kingdom · Faster Payments",
                     "fields": {"account_number": r"^\d{8}$", "sort_code": r"^\d{6}$"}},
    "USD_US_LOCAL": {"currency": "USD", "country": "US", "label": "USD · United States · ACH",
                     "fields": {"account_number": r"^\d{4,17}$", "aba": r"^\d{9}$"}},
}
_TEXT = re.compile(r"^[A-Za-z0-9 .,'&()/-]{2,80}$")


class BeneficiaryError(ValueError):
    pass


def _schema_body(c: dict[str, Any]) -> dict[str, Any]:
    return {"beneficiary": {"entity_type": "COMPANY", "bank_details": {"account_currency": c["currency"], "bank_country_code": c["country"]}},
            "payment_methods": ["LOCAL"]}


def schema(sandbox, corridor: str) -> dict[str, Any]:
    """What Airwallex says it requires for this corridor (POST /beneficiaries/schema), as readable field names."""
    c = CORRIDORS.get(corridor)
    if c is None:
        raise BeneficiaryError("unknown corridor")
    s = sandbox.beneficiary_schema(_schema_body(c)).get("schema", {})
    required = sorted(k.removeprefix("create_beneficiary_request.") for k, v in s.items()
                      if isinstance(v, dict) and v.get("relevant") and v.get("required") and v.get("type") != "object")
    return {"corridor": corridor, "label": c["label"], "provider_required": required, "form_fields": list(c["fields"])}


def build_body(corridor: str, form: dict[str, Any]) -> dict[str, Any]:
    c = CORRIDORS.get(corridor)
    if c is None:
        raise BeneficiaryError("unknown corridor")
    vals: dict[str, str] = {}
    for key in ("company_name", "bank_name", "street_address", "city"):
        v = str(form.get(key) or "").strip()
        if not _TEXT.match(v):
            raise BeneficiaryError(f"{key.replace('_', ' ')} must be 2-80 letters, digits or basic punctuation")
        vals[key] = v
    postcode = str(form.get("postcode") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9 -]{3,10}", postcode):
        raise BeneficiaryError("postcode must be 3-10 letters or digits")
    for key, pattern in c["fields"].items():
        v = re.sub(r"[\s-]", "", str(form.get(key) or "")).upper()
        if not re.fullmatch(pattern, v):
            raise BeneficiaryError(f"{key.replace('_', ' ')} has the wrong format for {c['label']}")
        vals[key] = v
    bank: dict[str, Any] = {"account_currency": c["currency"], "bank_country_code": c["country"],
                            "account_name": vals["company_name"], "bank_name": vals["bank_name"]}
    if corridor == "EUR_DE_LOCAL":
        bank["iban"] = vals["iban"]
    elif corridor == "GBP_GB_LOCAL":
        bank.update(account_number=vals["account_number"], account_routing_type1="sort_code", account_routing_value1=vals["sort_code"])
    else:
        bank.update(account_number=vals["account_number"], account_routing_type1="aba", account_routing_value1=vals["aba"])
    return {
        "beneficiary": {"entity_type": "COMPANY", "company_name": vals["company_name"],
                        "address": {"street_address": vals["street_address"], "city": vals["city"], "postcode": postcode,
                                    "country_code": c["country"]},
                        "bank_details": bank},
        "nickname": vals["company_name"][:50],
        "transfer_methods": ["LOCAL"],
    }


def summary(item: dict[str, Any]) -> dict[str, Any]:
    """Display row without full account numbers."""
    b = item.get("beneficiary") or {}
    bank = b.get("bank_details") or {}
    acct = str(bank.get("iban") or bank.get("account_number") or "")
    name = b.get("company_name") or " ".join(x for x in (b.get("first_name"), b.get("last_name")) if x) or bank.get("account_name") or ""
    return {"id": item.get("id"), "name": name, "currency": bank.get("account_currency"), "country": bank.get("bank_country_code"),
            "methods": item.get("transfer_methods") or [], "account": f"…{acct[-4:]}" if acct else ""}


def create(ctx, corridor: str, form: dict[str, Any], actor: str, customer_id: str | None = None) -> dict[str, Any]:
    body = build_body(corridor, form)
    if customer_id:
        with ctx.conn() as conn:
            if not db.row(conn, "SELECT id FROM customers WHERE id = ?", (customer_id,)):
                raise BeneficiaryError("customer_id does not exist")
    errors = ctx.sandbox.validate_beneficiary(body)
    if errors:
        fields = ", ".join(sorted({e["field"].removeprefix("beneficiary.") for e in errors}))
        raise BeneficiaryError(f"Airwallex rejected these fields: {fields}")
    created = ctx.sandbox.create_beneficiary(body)
    bid = created.get("id") or created.get("beneficiary_id")
    if not isinstance(bid, str) or not bid:
        raise ProviderError("beneficiary response did not contain an id")
    row = summary({**created, "id": bid, "beneficiary": created.get("beneficiary") or body["beneficiary"],
                   "transfer_methods": created.get("transfer_methods") or body["transfer_methods"]})
    with ctx.conn() as conn, db.transaction(conn):
        now = iso(ctx.clock.now())
        if customer_id:
            conn.execute("UPDATE customers SET refund_beneficiary = ?, updated_at = ? WHERE id = ?", (bid, now, customer_id))
        audit.record(conn, now, actor, "beneficiary.created", "beneficiary", bid,
                     {"corridor": corridor, "name": row["name"], "account": row["account"], "customer_id": customer_id})
    return {**row, "customer_id": customer_id}
