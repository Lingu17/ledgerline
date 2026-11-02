"""One explicit sandbox publishing attempt per balance-due draft.

Claim before network dispatch; ambiguous results never trigger an automatic retry.
This creates a collection link, never an outbound payment or an emailed request.
A paid link becomes a deposit on the normal path, idempotently on the link id, so ordinary matching settles the balance.
"""
import json
from urllib.parse import urlsplit

from . import audit, db, treasury
from .clock import iso
from .providers.base import ProviderError, ProviderUnsupported
from .reconcile import ingest_deposit, invoice_views


def publish(ctx, link_id: str, actor: str):
    with ctx.conn() as conn, db.transaction(conn):
        link = db.row(conn, 'SELECT * FROM payment_links WHERE id = ?', (link_id,))
        if not link:
            raise ValueError('unknown balance-due draft')
        if link['status'] != 'local_draft':
            return link  # Includes unknown outcomes: never submit again.
        invoice = invoice_views(conn).get(link['invoice_id'])
        if not invoice or invoice.status != 'open' or invoice.remaining_minor != link['amount_minor']:
            raise ValueError('invoice balance changed; this draft cannot be published')
        conn.execute("UPDATE payment_links SET status='creating', note=? WHERE id=?",
                     ('Sandbox creation requested; outcome pending. Do not resubmit.', link_id))
    try:
        result = ctx.sandbox.create_payment_link(title=f"Balance due on {link['invoice_id']}",
                    amount_minor=link['amount_minor'], currency=link['currency'], reference=link['invoice_id'])
        parsed = urlsplit(result.url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ProviderError('payment link response had no safe HTTPS URL')
        status, url, provider_id = 'sandbox_created', result.url, result.provider_id
        note = 'Hosted payment link returned by Airwallex sandbox. Nothing was emailed.'
    except (ProviderError, ProviderUnsupported) as exc:
        status, url, provider_id = 'draft_fallback', None, None
        note = f'Airwallex link not available ({exc}). Labelled draft only; nothing emailed. No automatic retry.'
    except Exception:
        status, url, provider_id = 'creation_unknown', None, None
        note = 'Provider result unknown. No URL recorded and no automatic retry; operator reconciliation required.'
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute('UPDATE payment_links SET status=?, url=?, provider_id=?, note=? WHERE id=?',
                     (status, url, provider_id, note, link_id))
        audit.record(conn, iso(ctx.clock.now()), actor, f'payment_link.{status}', 'invoice', link['invoice_id'],
                     {'link_id': link_id, 'amount_minor': link['amount_minor'], 'note': note})
        return db.row(conn, 'SELECT * FROM payment_links WHERE id=?', (link_id,))


def check(ctx, link_id: str, actor: str):
    """Ask the bank whether a created link was paid, and book it once if so. Safe to call repeatedly and concurrently."""
    with ctx.conn() as conn:
        link = db.row(conn, 'SELECT * FROM payment_links WHERE id = ?', (link_id,))
    if not link:
        raise ValueError('unknown payment link')
    if link['status'] != 'sandbox_created' or not link['provider_id'] or ctx.sandbox is None:
        return link
    if not ctx.sandbox.payment_link_paid(link['provider_id']):
        return link
    with ctx.conn() as conn, db.transaction(conn):
        link = db.row(conn, 'SELECT * FROM payment_links WHERE id = ?', (link_id,))
        if link['status'] != 'sandbox_created':
            return link
        now = iso(ctx.clock.now())
        customer = db.row(conn, 'SELECT c.name, c.payer_names FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.id = ?', (link['invoice_id'],))
        payer = (json.loads(customer['payer_names']) or [customer['name']])[0]
        deposit_id, _ = ingest_deposit(conn, ctx, {
            'provider_ref': f"LINK:{link['provider_id']}", 'currency': link['currency'], 'amount_minor': link['amount_minor'],
            'payer_name': payer, 'reference': link['invoice_id'], 'received_at': now}, source='airwallex_payment_link')
        conn.execute("UPDATE payment_links SET status='paid', note=? WHERE id=?", (f'Airwallex reports this link paid; booked as {deposit_id}.', link_id))
        audit.record(conn, now, actor, 'payment_link.paid', 'invoice', link['invoice_id'],
                     {'link_id': link_id, 'deposit_id': deposit_id, 'amount_minor': link['amount_minor']})
    treasury.refresh_decisions(ctx, f"balance payment for {link['invoice_id']} received", actor)
    with ctx.conn() as conn:
        return db.row(conn, 'SELECT * FROM payment_links WHERE id = ?', (link_id,))
