"""Webhook verification and deduplicated ingestion.

Signature: hex(HMAC-SHA256(secret, x-timestamp + raw_body)), compared in
constant time. x-timestamp is Unix milliseconds and must be within the
configured tolerance. Event ids are deduplicated in the same DB transaction
that applies the event, so a replay can never trigger a second action.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from . import audit, db
from .clock import iso, parse_iso
from .context import AppContext
from .money import MoneyError, to_minor, validate_currency
from .reconcile import ingest_deposit

DEPOSIT_EVENTS = {"deposit.settled"}


class WebhookRejected(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def sign(secret: str, timestamp_ms: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode(), timestamp_ms.encode() + raw_body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, timestamp_ms: str | None, signature: str | None, raw_body: bytes, *,
                     now_ms: int, tolerance_s: int) -> None:
    if not timestamp_ms or not signature:
        raise WebhookRejected(401, "missing x-timestamp or x-signature")
    if not timestamp_ms.isdigit():
        raise WebhookRejected(401, "malformed x-timestamp")
    if abs(now_ms - int(timestamp_ms)) > tolerance_s * 1000:
        raise WebhookRejected(401, "timestamp outside tolerance")
    expected = sign(secret, timestamp_ms, raw_body)
    if not hmac.compare_digest(expected, signature.strip().lower()):
        raise WebhookRejected(401, "signature mismatch")


def _parse_deposit(event: dict[str, Any], hints: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse the documented deposit.settled shape: deposit fields directly under `data`.

    The official settled example carries no payer block, so payer name and
    reference recorded when *we* created a sandbox simulation (deposit_hints)
    fill the gap. A `payer: {name}` object is honoured when present.
    """
    data = event.get("data")
    if not isinstance(data, dict):
        raise WebhookRejected(400, "data must be an object")
    dep_id = data.get("id")
    if not isinstance(dep_id, str) or not dep_id.strip():
        raise WebhookRejected(400, "data.id must be a non-empty string")
    if str(data.get("status", "")).upper() != "SETTLED":
        raise WebhookRejected(400, "only SETTLED deposits are ingested")
    currency = data.get("currency")
    amount = data.get("amount")
    if not isinstance(currency, str):
        raise WebhookRejected(400, "data.currency must be a string")
    if isinstance(amount, bool) or not isinstance(amount, (int, float, str)):
        raise WebhookRejected(400, "data.amount must be a number")
    try:
        ccy = validate_currency(currency)
        amount_minor = to_minor(amount, ccy)
    except MoneyError as exc:
        raise WebhookRejected(400, f"invalid amount/currency: {exc}") from exc
    if amount_minor <= 0:
        raise WebhookRejected(400, "deposit amount must be positive")
    settled = data.get("settled_at") or data.get("created_at")
    if not isinstance(settled, str):
        raise WebhookRejected(400, "data.settled_at must be an ISO 8601 string")
    try:
        received_at = iso(parse_iso(settled))
    except ValueError as exc:
        raise WebhookRejected(400, f"data.settled_at is not ISO 8601: {settled!r}") from exc
    payer = data.get("payer")
    if payer is not None and not isinstance(payer, dict):
        raise WebhookRejected(400, "data.payer must be an object when present")
    payer_name = (payer or {}).get("name")
    if payer_name is not None and not isinstance(payer_name, str):
        raise WebhookRejected(400, "data.payer.name must be a string")
    reference = data.get("reference")
    if reference is not None and not isinstance(reference, str):
        raise WebhookRejected(400, "data.reference must be a string")
    hints = hints or {}
    return {
        "provider_ref": dep_id.strip(),
        "currency": ccy,
        "amount_minor": amount_minor,
        "payer_name": payer_name or hints.get("payer_name") or "UNKNOWN PAYER",
        "reference": reference if reference is not None else hints.get("reference", ""),
        "received_at": received_at,
        "global_account_id": data.get("funding_source_id") if isinstance(data.get("funding_source_id"), str) else None,
    }


def handle(ctx: AppContext, *, raw_body: bytes, timestamp_ms: str | None, signature: str | None, secret: str,
           source: str, now_ms: int | None = None) -> dict[str, Any]:
    with ctx.conn() as conn:
        tolerance = ctx.policy(conn)["webhook_tolerance_seconds"]
    if now_ms is None:
        now_ms = int(ctx.clock.now().timestamp() * 1000) if ctx.clock else int(time.time() * 1000)
    verify_signature(secret, timestamp_ms, signature, raw_body, now_ms=now_ms, tolerance_s=tolerance)
    try:
        event = json.loads(raw_body)
    except ValueError as exc:
        raise WebhookRejected(400, "body is not JSON") from exc
    if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not isinstance(event.get("name"), str):
        raise WebhookRejected(400, "event needs string id and name")

    with ctx.conn() as conn, db.transaction(conn):
        now = iso(ctx.clock.now())
        if db.row(conn, "SELECT event_id FROM webhook_events WHERE event_id = ?", (event["id"],)):
            audit.record(conn, now, "webhook", "webhook.duplicate_ignored", "webhook", event["id"], {"name": event["name"]})
            return {"status": "duplicate", "event_id": event["id"]}
        result: dict[str, Any] = {"status": "ignored", "event_id": event["id"]}
        if event["name"] in DEPOSIT_EVENTS:
            data = event.get("data")
            hint = db.row(conn, "SELECT payer_name, reference FROM deposit_hints WHERE provider_ref = ?",
                          (data.get("id"),)) if isinstance(data, dict) and isinstance(data.get("id"), str) else None
            fields = _parse_deposit(event, hint)
            dep_id, created = ingest_deposit(conn, ctx, fields, source=source, global_account_id=fields.get("global_account_id"))
            result = {"status": "processed" if created else "deposit_already_known", "event_id": event["id"], "deposit_id": dep_id}
        conn.execute(
            "INSERT INTO webhook_events VALUES (?,?,?,?,?)",
            (event["id"], event["name"], hashlib.sha256(raw_body).hexdigest(), now, result["status"]),
        )
        audit.record(conn, now, "webhook", "webhook.accepted", "webhook", event["id"], result)
        return result


def build_deposit_event(event_id: str, fields: dict[str, Any], amount_major: str) -> bytes:
    """Local workspace: a deposit.settled payload in the documented flat shape.

    It adds a payer block (not present in the official settled example) because a
    local simulation has no earlier deposit.pending event to learn the payer from.
    """
    return json.dumps({
        "id": event_id,
        "name": "deposit.settled",
        "accountId": "acct_local_workspace",
        "data": {
            "id": fields["provider_ref"],
            "type": "LOCAL_SIMULATION",
            "status": "SETTLED",
            "created_at": fields["received_at"],
            "settled_at": fields["received_at"],
            "currency": fields["currency"],
            "amount": amount_major,
            "reference": fields["reference"],
            "payer": {"name": fields["payer_name"]},
        },
    }, separators=(",", ":")).encode()
