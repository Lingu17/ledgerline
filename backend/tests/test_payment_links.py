from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from ledgerline import audit, db, ledger, payment_links, watcher
from ledgerline.demo import run_step
from ledgerline.providers.base import PaymentLinkResult, ProviderError
from ledgerline.reconcile import invoice_views


def prepare(ctx, result=None, error=None):
    run_step(ctx, 'deposits', 'tester')
    with ctx.conn() as conn:
        link = db.row(conn, "SELECT * FROM payment_links WHERE invoice_id='INV-2260'")
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        if error:
            raise error
        return result or PaymentLinkResult('provider-link', 'https://checkout.example.test/returned-by-provider')
    ctx.sandbox = SimpleNamespace(create_payment_link=create)
    return link, calls


def test_concurrent_publish_attempt_is_once_and_uses_exact_balance(ctx):
    link, calls = prepare(ctx)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: payment_links.publish(ctx, link['id'], 'owner'), range(4)))
    assert len(calls) == 1
    assert calls[0]['amount_minor'] == 120_000 and calls[0]['currency'] == 'GBP'
    assert payment_links.publish(ctx, link['id'], 'owner')['status'] == 'sandbox_created'
    assert len(calls) == 1


@pytest.mark.parametrize('error,expected', [
    (ProviderError('POST /pa/payment_links/create: HTTP 403 access_denied'), 'draft_fallback'),
    (TimeoutError('test-only'), 'creation_unknown'),
])
def test_refusal_or_unknown_outcome_never_fabricates_url_or_retries(ctx, error, expected):
    link, calls = prepare(ctx, error=error)
    result = payment_links.publish(ctx, link['id'], 'owner')
    assert result['status'] == expected and result['url'] is None
    assert payment_links.publish(ctx, link['id'], 'owner')['url'] is None
    assert len(calls) == 1


def test_changed_invoice_balance_refuses_dispatch(ctx):
    link, calls = prepare(ctx)
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE invoices SET prior_paid_minor=1 WHERE id='INV-2260'")
    with pytest.raises(ValueError, match='balance changed'):
        payment_links.publish(ctx, link['id'], 'owner')
    assert calls == []


def test_unallowlisted_owner_cannot_publish(client):
    assert client.post('/api/integrations/sandbox/payment-links/PL-foreign/publish').status_code == 403


def test_unsafe_provider_url_is_not_exposed(ctx):
    link, calls = prepare(ctx, result=PaymentLinkResult('bad', 'javascript:alert(1)'))
    result = payment_links.publish(ctx, link['id'], 'owner')
    assert result['url'] is None and result['status'] == 'draft_fallback'


def published(ctx, paid):
    link, _ = prepare(ctx)
    payment_links.publish(ctx, link['id'], 'owner')
    ctx.sandbox.payment_link_paid = lambda _pid: paid
    return link


def test_unpaid_link_books_nothing(ctx):
    link = published(ctx, paid=False)
    with ctx.conn() as conn:
        before = conn.execute('SELECT COUNT(*) FROM deposits').fetchone()[0]
    assert payment_links.check(ctx, link['id'], 'op')['status'] == 'sandbox_created'
    with ctx.conn() as conn:
        assert conn.execute('SELECT COUNT(*) FROM deposits').fetchone()[0] == before


def test_paid_link_settles_the_exact_balance_once_even_concurrently(ctx):
    link = published(ctx, paid=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: payment_links.check(ctx, link['id'], 'op'), range(4)))
    assert {r['status'] for r in results} == {'paid'}
    with ctx.conn() as conn:
        rows = db.rows(conn, "SELECT status, amount_minor FROM deposits WHERE source = 'airwallex_payment_link'")
        assert rows == [{'status': 'matched', 'amount_minor': 120_000}]
        assert invoice_views(conn)['INV-2260'].remaining_minor == 0
        assert ledger.conservation(conn)['all_balanced'] and audit.verify_chain(conn)['ok']


def test_check_on_a_draft_never_asks_the_bank(ctx):
    link, _ = prepare(ctx)
    assert payment_links.check(ctx, link['id'], 'op')['status'] == 'local_draft'


def test_unallowlisted_member_cannot_check(client):
    assert client.post('/api/integrations/sandbox/payment-links/PL-foreign/check').status_code == 403


class FakeControl:
    def __init__(self, orgs):
        self.orgs = orgs

    def all_org_ids(self):
        return list(self.orgs)

    def org(self, org_id):
        return self.orgs[org_id]


def connected(org_id='org_a'):
    return {org_id: {'bank_mode': 'airwallex_sandbox', 'created_at': '2020-01-01T00:00:00Z'}}


def test_watcher_books_paid_links_and_skips_practice_companies(ctx):
    link = published(ctx, paid=True)
    orgs = SimpleNamespace(get=lambda _id: ctx)
    control = FakeControl({**connected(), 'org_b': {'bank_mode': 'local'}})
    assert watcher.sweep(orgs, control) == 1
    with ctx.conn() as conn:
        assert db.row(conn, 'SELECT status FROM payment_links WHERE id = ?', (link['id'],))['status'] == 'paid'


def test_watcher_ignores_old_links_and_survives_a_failing_organization(ctx):
    link = published(ctx, paid=True)
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute("UPDATE payment_links SET created_at = '2020-01-01T00:00:00Z' WHERE id = ?", (link['id'],))

    def get(org_id):
        if org_id == 'org_bad':
            raise RuntimeError('test-only')
        return ctx
    control = FakeControl({**connected('org_bad'), **connected('org_a')})
    assert watcher.sweep(SimpleNamespace(get=get), control) == 1
    with ctx.conn() as conn:
        assert db.row(conn, 'SELECT status FROM payment_links WHERE id = ?', (link['id'],))['status'] == 'sandbox_created'
