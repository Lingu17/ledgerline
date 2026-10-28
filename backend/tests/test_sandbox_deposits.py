"""Sandbox receipt finality and retries; the provider here is deliberately simulated."""
from types import SimpleNamespace

import pytest

from ledgerline import db, demo


def test_pending_simulations_never_invent_settled_funds_and_retry_does_not_repeat(ctx):
    calls = []
    def simulate(**fields):
        calls.append(fields)
        return {"id": f"sandbox-receipt-{len(calls)}", "status": "PENDING", "currency": fields['currency']}
    ctx.sandbox = SimpleNamespace(simulate_deposit=simulate)
    ctx.settings.airwallex_global_account_ids = {c: f"ga_{c}" for c in ('USD', 'EUR', 'GBP')}
    first = demo.ingest_scenario_deposits(ctx)
    second = demo.ingest_scenario_deposits(ctx)
    assert len(calls) == 6
    assert first == second and all(r['status'] == 'awaiting_webhook' for r in first)
    with ctx.conn() as conn:
        assert db.row(conn, 'SELECT COUNT(*) AS n FROM deposits')['n'] == 0
        assert db.row(conn, 'SELECT COUNT(*) AS n FROM deposit_hints')['n'] == 6


def test_ambiguous_simulation_is_never_automatically_repeated(ctx):
    calls = []
    def simulate(**fields):
        calls.append(fields)
        raise TimeoutError('test-only ambiguous response')
    ctx.sandbox = SimpleNamespace(simulate_deposit=simulate)
    ctx.settings.airwallex_global_account_ids = {c: f"ga_{c}" for c in ('USD', 'EUR', 'GBP')}
    with pytest.raises(TimeoutError):
        demo.ingest_scenario_deposits(ctx)
    with pytest.raises(demo.DemoError, match='reconciliation'):
        demo.ingest_scenario_deposits(ctx)
    assert len(calls) == 1


def test_missing_currency_mapping_creates_nothing(ctx):
    calls = []
    ctx.sandbox = SimpleNamespace(simulate_deposit=lambda **fields: calls.append(fields))
    ctx.settings.airwallex_global_account_ids = {'EUR': 'ga_eur'}
    with pytest.raises(demo.DemoError, match='USD'):
        demo.ingest_scenario_deposits(ctx)
    assert not calls
