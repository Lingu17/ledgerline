"""The audit log detects tampering, and a stored plan replays to the identical answer."""
import json
import sqlite3
from datetime import timedelta

import pytest

from ledgerline import audit, db, treasury, workspace
from ledgerline.migrations import TENANT, migrate


@pytest.fixture
def empty(settings):
    from ledgerline.api.app import build_context

    c = build_context(settings)
    workspace.set_opening_balance(c, {"currency": "EUR", "amount": "3000"}, "owner")
    workspace.set_opening_balance(c, {"currency": "USD", "amount": "20000"}, "owner")
    for name, amount in (("Hosting", "500"), ("Supplier", "1500")):
        due = (c.clock.now() + timedelta(days=2)).date().isoformat()
        workspace.create_obligation(c, {"payee": name, "currency": "EUR", "amount": amount, "due_date": due}, "op")
    treasury.refresh_decisions(c, "test")
    return c


def verify(ctx):
    with ctx.conn() as conn:
        return audit.verify_chain(conn)


def tamper(ctx, sql, params=()):
    with ctx.conn() as conn, db.transaction(conn):
        conn.execute(sql, params)


def test_intact_log_verifies(empty):
    r = verify(empty)
    assert r["ok"] and r["events"] >= 5 and len(r["head"]) == 64


def test_edited_event_is_caught(empty):
    tamper(empty, "UPDATE audit_events SET detail = ? WHERE id = 2", ('{"amount_minor": 1}',))
    r = verify(empty)
    assert not r["ok"] and r["broken_at"] == 2


def test_changed_actor_is_caught(empty):
    tamper(empty, "UPDATE audit_events SET actor = 'someone-else' WHERE id = 3")
    assert verify(empty)["broken_at"] == 3


def test_deleted_middle_event_is_caught(empty):
    tamper(empty, "DELETE FROM audit_events WHERE id = 2")
    assert not verify(empty)["ok"]


def test_deleted_newest_event_is_caught(empty):
    tamper(empty, "DELETE FROM audit_events WHERE id = (SELECT MAX(id) FROM audit_events)")
    r = verify(empty)
    assert not r["ok"] and "newest" in r["problem"]


def test_older_logs_are_chained_by_the_upgrade(tmp_path):
    from ledgerline.db import SCHEMA

    conn = sqlite3.connect(tmp_path / "old.sqlite3", isolation_level=None)
    conn.executescript(SCHEMA)
    migrate(conn, [m for m in TENANT if m[0] < 6])
    for i in range(3):
        conn.execute("INSERT INTO audit_events(at, actor, action, entity_type, entity_id, detail) VALUES (?,?,?,?,?,?)",
                     (f"2026-10-0{i + 1}T00:00:00Z", "old", "x", "y", "z", "{}"))
    assert migrate(conn, TENANT) == [6, 7, 8, 9, 10]
    conn.row_factory = sqlite3.Row
    r = audit.verify_chain(conn)
    assert r["ok"] and r["events"] == 3
    conn.close()


def run_id(ctx):
    return treasury.list_plan_runs(ctx)[0]["id"]


def test_plan_replays_identically_even_after_the_world_changes(empty):
    rid = run_id(empty)
    before = treasury.replay_plan_run(empty, rid)
    assert before["ok"] and before["identical"]
    # New bills and new cash change today's plan, not what that run decided.
    due = (empty.clock.now() + timedelta(days=1)).date().isoformat()
    workspace.create_obligation(empty, {"payee": "Tax", "currency": "EUR", "amount": "900", "due_date": due, "priority": "critical"}, "op")
    treasury.refresh_decisions(empty, "new bill")
    assert treasury.replay_plan_run(empty, rid)["decisions"] == before["decisions"]
    assert len(treasury.list_plan_runs(empty)) == 2


def test_changed_stored_decision_is_caught(empty):
    rid = run_id(empty)
    with empty.conn() as conn:
        out = json.loads(db.row(conn, "SELECT output FROM plan_runs WHERE id = ?", (rid,))["output"])
    out[0]["decision"] = "escalate"
    tamper(empty, "UPDATE plan_runs SET output = ? WHERE id = ?", (json.dumps(out), rid))
    r = treasury.replay_plan_run(empty, rid)
    assert not r["ok"] and not r["identical"]


def test_changed_inputs_are_caught_even_with_a_matching_hash_column(empty):
    from ledgerline import crypto

    rid = run_id(empty)
    with empty.conn() as conn:
        inputs = json.loads(db.row(conn, "SELECT inputs FROM plan_runs WHERE id = ?", (rid,))["inputs"])
    inputs["available"]["EUR"] = 9_999_999
    tamper(empty, "UPDATE plan_runs SET inputs = ?, inputs_hash = ? WHERE id = ?", (json.dumps(inputs), crypto.scope_hash(inputs), rid))
    r = treasury.replay_plan_run(empty, rid)
    assert not r["ok"] and not r["inputs_untampered"]


def test_concurrent_writers_keep_one_unbroken_chain(empty):
    import threading

    due = (empty.clock.now() + timedelta(days=3)).date().isoformat()
    errors = []

    def writer(n):
        try:
            for i in range(5):
                workspace.create_obligation(empty, {"payee": f"Vendor {n} {i}", "currency": "USD", "amount": "1", "due_date": due}, "op")
                treasury.refresh_decisions(empty, "concurrent")
        except Exception as exc:  # noqa: BLE001 - reported by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert verify(empty)["ok"]


def test_every_audit_write_in_the_full_reference_flow_stays_chained(client):
    for step in ("deposits", "links", "agents", "treasury", "approve", "bank_sent", "bank_paid"):
        client.post("/api/demo/step", json={"step": step})
    r = client.get("/api/audit/verify").json()
    assert r["ok"] and r["events"] > 20


def test_replay_needs_no_network_or_clock():
    out = treasury.plan_bills({"now": "2026-11-02T00:00:00Z", "available": {"EUR": 100_000}, "surplus": {"EUR": 0}, "rates": {},
                               "bills": [{"id": "B", "payee": "x", "currency": "EUR", "amount_minor": 50_000, "due_at": "2026-11-03T00:00:00Z", "priority": "normal", "defer_until": None}]})
    assert out[0]["decision"] == "fund"


def test_api_viewer_can_verify_and_export_carries_the_head(client, app):
    from .test_saas import _invite_and_join

    client.post("/api/demo/step", json={"step": "deposits"})
    assert client.post("/api/treasury/practice-squeeze").status_code == 200
    viewer = _invite_and_join(client, app, "v2@northbeam.test", "viewer")
    r = viewer.get("/api/audit/verify").json()
    assert r["ok"]
    rid = viewer.get("/api/treasury/plan-runs").json()[0]["id"]
    assert viewer.get(f"/api/treasury/plan-runs/{rid}/replay").json()["ok"]
    export = client.get("/api/audit/export").json()
    assert export["audit_chain"]["ok"] and export["plan_runs"]
    assert client.post("/api/demo/step", json={"step": "seed"}).status_code == 200  # a practice reset starts a fresh, valid chain
    assert client.get("/api/audit/verify").json()["ok"]
