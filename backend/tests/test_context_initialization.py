"""Concurrent first requests must not run tenant initialization simultaneously."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from ledgerline.clock import Clock
from ledgerline.context import AppContext


def test_concurrent_first_connections_initialize_once(settings, monkeypatch):
    from ledgerline import migrations
    original = migrations.migrate
    calls = []
    def migrate(conn, steps):
        calls.append(1)
        time.sleep(0.03)  # make the initial-request race deterministic
        return original(conn, steps)
    monkeypatch.setattr(migrations, 'migrate', migrate)
    ctx = AppContext(settings=settings, clock=Clock(), provider=None)
    barrier = threading.Barrier(5)
    def connect(_):
        barrier.wait(timeout=5)
        with ctx.conn() as conn:
            return conn.execute('SELECT 1').fetchone()[0]
    with ThreadPoolExecutor(max_workers=5) as executor:
        assert list(executor.map(connect, range(5))) == [1] * 5
    assert len(calls) == 1


def test_failed_initialization_closes_connection_and_can_retry(settings, monkeypatch):
    from ledgerline import db, migrations
    class Connection:
        closed = False
        def close(self):
            self.closed = True
    conn = Connection()
    monkeypatch.setattr(db, 'connect', lambda _: conn)
    def fail(*_):
        raise RuntimeError('test-only migration failure')
    monkeypatch.setattr(migrations, 'migrate', fail)
    ctx = AppContext(settings=settings, clock=Clock(), provider=None)
    with pytest.raises(RuntimeError, match='migration failure'):
        ctx.connect()
    assert conn.closed and not ctx._initialised
