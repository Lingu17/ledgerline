from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import uuid

import pytest

from ledgerline import db, sandbox_receipts as receipts
from .conftest import new_client, signup


def configure(ctx):
    calls = []
    def simulate(**kw):
        calls.append(kw)
        return {'id': 'provider-receipt', 'status': 'PENDING', 'currency': 'EUR'}
    resource = {'id': 'provider-receipt', 'status': 'PENDING', 'amount': 1.23, 'currency': 'EUR',
                'created_at': '2026-10-28T00:00:00Z', 'global_account_id': 'ga_eur'}
    ctx.sandbox = SimpleNamespace(simulate_deposit=simulate, get_deposit=lambda _: resource)
    ctx.settings.airwallex_global_account_ids = {'EUR': 'ga_eur'}
    return calls, resource


def create(ctx, request_id=None, **extra):
    return receipts.create(ctx, request_id or str(uuid.uuid4()), 'EUR', extra.get('amount', '1.23'),
                           'Synthetic payer', extra.get('reference', 'TEST-RECEIPT'), 'owner@test.example')


def test_concurrent_receipt_requests_are_submitted_once(ctx):
    calls, _ = configure(ctx)
    request_id = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: create(ctx, request_id), range(4)))
    assert len(calls) == 1 and all(r['request_id'] == request_id for r in results)
    assert create(ctx, request_id)['provider_ref'] == 'provider-receipt'
    with pytest.raises(receipts.SandboxReceiptError, match='different'):
        create(ctx, request_id, amount='2.00')


def test_sync_requires_real_settlement_and_is_idempotent(ctx):
    _, resource = configure(ctx)
    create(ctx)
    assert receipts.sync(ctx, 'owner')[0]['status'] == 'awaiting_settlement'
    with ctx.conn() as conn:
        assert db.row(conn, 'SELECT COUNT(*) AS n FROM deposits')['n'] == 0
    resource.update(status='SETTLED', settled_at='2026-10-28T00:00:01Z')
    assert receipts.sync(ctx, 'owner')[0]['status'] == 'settled'
    assert receipts.sync(ctx, 'owner')[0]['status'] == 'settled'
    with ctx.conn() as conn:
        assert db.row(conn, 'SELECT COUNT(*) AS n FROM deposits')['n'] == 1
        assert db.row(conn, 'SELECT amount_minor, source FROM deposits')['source'] == 'airwallex_sandbox_poll'


def test_timeout_after_simulation_never_resubmits(ctx):
    calls, _ = configure(ctx)
    def ambiguous(**kw):
        calls.append(kw)
        raise TimeoutError('test-only')
    ctx.sandbox.simulate_deposit = ambiguous
    request_id = str(uuid.uuid4())
    assert create(ctx, request_id)['status'] == 'needs_reconciliation'
    assert create(ctx, request_id)['status'] == 'needs_reconciliation'
    assert len(calls) == 1


@pytest.mark.parametrize('changed', [{'currency': 'USD'}, {'amount': 2.00}, {'id': 'foreign-receipt'}, {'global_account_id': 'foreign-account'}])
def test_sync_refuses_changed_provider_receipt(ctx, changed):
    _, resource = configure(ctx)
    create(ctx)
    resource.update(status='SETTLED', settled_at='2026-10-28T00:00:01Z', **changed)
    with pytest.raises(receipts.SandboxReceiptError):
        receipts.sync(ctx, 'owner')
    with ctx.conn() as conn:
        assert db.row(conn, 'SELECT COUNT(*) AS n FROM deposits')['n'] == 0


def test_judge_and_viewer_cannot_use_receipt_actions(client, app):
    body = {'request_id': str(uuid.uuid4()), 'currency': 'EUR', 'amount': '1.23', 'payer_name': 'Test', 'reference': 'Test'}
    assert client.post('/api/integrations/sandbox/deposits', json=body).status_code == 403
    from .test_saas import _invite_and_join
    for role in ('viewer', 'operator'):
        member = _invite_and_join(client, app, f'sandbox-{role}@test.example', role)
        assert member.post('/api/integrations/sandbox/deposits', json=body).status_code == 403
        assert member.post('/api/integrations/sandbox/deposits/sync').status_code == 403
        assert member.get('/api/integrations/sandbox/deposits').status_code == 403
    # An unallowlisted second organization cannot see request history either.
    other = new_client(app)
    signup(other, email='other-sandbox@test.example', start_with='empty')
    assert other.get('/api/integrations/sandbox/deposits').status_code == 403


def test_allowlist_is_rechecked_for_every_action(client, app):
    app.state.settings.airwallex_client_id = 'test-only-id'
    app.state.settings.airwallex_api_key = 'test-only-key'
    app.state.settings.sandbox_org_ids = frozenset({client.org_id})
    assert client.put('/api/organization', json={'bank_mode': 'airwallex_sandbox', 'airwallex_global_accounts': {'EUR': 'ga_eur'}}).status_code == 200
    ctx = app.state.orgs.get(client.org_id)
    configure(ctx)
    body = {'request_id': str(uuid.uuid4()), 'currency': 'EUR', 'amount': '1.23', 'payer_name': 'Test', 'reference': 'Test'}
    assert client.post('/api/integrations/sandbox/deposits', json=body).status_code == 200
    assert client.post('/api/integrations/sandbox/deposits', json={**body, 'amount': True}).status_code == 422
    assert client.post('/api/integrations/sandbox/deposits', json={**body, 'amount': '-1.00'}).status_code == 422
    assert client.post('/api/integrations/sandbox/deposits', json={**body, 'reference': 'changed'}).status_code == 409
    app.state.settings.sandbox_org_ids = frozenset()
    assert client.post('/api/integrations/sandbox/deposits/sync').status_code == 403
