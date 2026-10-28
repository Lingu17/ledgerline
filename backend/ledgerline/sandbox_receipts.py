"""Owner sandbox receipt exercises. No credentials or arbitrary provider paths in the API.

Only receipts created by this organization are polled. A timed-out simulation is
never automatically resubmitted: that API has no documented idempotency parameter.
"""
from __future__ import annotations

import hashlib
import json

from . import audit, db
from .clock import iso
from .money import to_minor, validate_minor
from .providers.base import ProviderError
from .reconcile import ingest_deposit
from .webhooks import _parse_deposit

PREFIX = 'sandbox_receipt:'


class SandboxReceiptError(ValueError):
    pass


def records(ctx):
    with ctx.conn() as conn:
        rows = db.rows(conn, "SELECT value FROM settings WHERE key LIKE ? ORDER BY key LIMIT 100", (PREFIX + '%',))
    return [json.loads(row['value']) for row in rows]


def create(ctx, request_id, currency, amount, payer_name, reference, actor):
    minor = validate_minor(to_minor(amount, currency))
    if minor > 1_000_000:
        raise SandboxReceiptError('sandbox receipt exercises are limited to 10,000 major units')
    gid = ctx.settings.airwallex_global_account_ids.get(currency)
    if not gid:
        raise SandboxReceiptError('configure a dedicated receiving account for this currency first')
    payload = dict(currency=currency, amount_minor=minor, payer_name=payer_name, reference=reference, global_account_id=gid)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    key = PREFIX + request_id
    with ctx.conn() as conn, db.transaction(conn):
        previous = db.get_setting(conn, key)
        if previous:
            if previous['payload_hash'] != digest:
                raise SandboxReceiptError('this request id already belongs to different deposit terms')
            return previous
        if len(db.rows(conn, "SELECT key FROM settings WHERE key LIKE ?", (PREFIX + '%',))) >= 100:
            raise SandboxReceiptError('sandbox receipt exercise limit reached')
        record = dict(request_id=request_id, payload_hash=digest, **payload, status='submitting', created_at=iso(ctx.clock.now()))
        db.set_setting(conn, key, record)
        audit.record(conn, record['created_at'], actor, 'sandbox.deposit_requested', 'sandbox_receipt', request_id,
                     {'currency': currency, 'amount_minor': minor})
    try:
        created = ctx.sandbox.simulate_deposit(global_account_id=gid, currency=currency, amount_minor=minor,
                                               payer_name=payer_name, reference=reference)
        provider_id = created.get('id') or created.get('deposit_id')
        if not isinstance(provider_id, str) or not provider_id:
            raise ProviderError('simulation response did not contain a deposit id')
        record.update(provider_ref=provider_id, status='awaiting_settlement', provider_status=created.get('status', 'UNKNOWN'))
        with ctx.conn() as conn, db.transaction(conn):
            db.set_setting(conn, key, record)
            conn.execute('INSERT OR IGNORE INTO deposit_hints VALUES (?,?,?,?)',
                         (provider_id, payer_name, reference, iso(ctx.clock.now())))
        return record
    except Exception as exc:
        record.update(status='needs_reconciliation', error_type=type(exc).__name__)
        with ctx.conn() as conn, db.transaction(conn):
            db.set_setting(conn, key, record)
        # Do not expose provider credentials, raw responses or a retry that might duplicate the deposit.
        return record


def sync(ctx, actor):
    results = []
    for record in records(ctx):
        if record['status'] == 'settled':
            results.append(record)
            continue
        if not record.get('provider_ref'):
            results.append(record)
            continue
        resource = ctx.sandbox.get_deposit(record['provider_ref'])
        if resource.get('id') != record['provider_ref']:
            raise SandboxReceiptError('provider returned a different receipt id')
        record['provider_status'] = resource.get('status', 'UNKNOWN')
        if str(resource.get('status', '')).upper() == 'SETTLED':
            fields = _parse_deposit({'data': resource}, record)
            if fields['currency'] != record['currency'] or fields['amount_minor'] != record['amount_minor']:
                raise SandboxReceiptError('provider receipt amount or currency differs from the requested simulation')
            if fields.get('global_account_id') and fields['global_account_id'] != record['global_account_id']:
                raise SandboxReceiptError('provider receipt belongs to another global account')
            with ctx.conn() as conn, db.transaction(conn):
                deposit_id, _ = ingest_deposit(conn, ctx, fields, source='airwallex_sandbox_poll',
                                               global_account_id=record['global_account_id'])
                record.update(status='settled', deposit_id=deposit_id)
                db.set_setting(conn, PREFIX + record['request_id'], record)
                audit.record(conn, iso(ctx.clock.now()), actor, 'sandbox.deposit_polled', 'deposit', deposit_id,
                             {'provider_ref': record['provider_ref'], 'provider_status': 'SETTLED'})
        else:
            if str(resource.get('status', '')).upper() in ('REJECTED', 'REVERSED'):
                record['status'] = str(resource['status']).lower()
            with ctx.conn() as conn, db.transaction(conn):
                db.set_setting(conn, PREFIX + record['request_id'], record)
        results.append(record)
    return results
