from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from ledgerline import db, payment_links
from ledgerline.demo import run_step
from ledgerline.providers.base import PaymentLinkResult, ProviderError


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
