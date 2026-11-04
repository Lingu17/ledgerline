"""Try to tamper, in a practice company only: change one audit event the way someone with database access could, so a
person can watch the hash chain catch it at that event, then put it back.

The change is made directly in the table, as an attacker would, and nothing is recorded while it stands. Restoring
puts the original text back, checks the chain is whole again, and only then records that the demo was tried. Real
companies refuse both. A backup taken while a demo is open is checked with the change put back (see `undo`).
"""
from __future__ import annotations

import json
from typing import Any

from . import audit, db
from .clock import iso
from .context import AppContext
from .payouts import PracticeOnly

SETTING = "practice_tamper"


class TamperError(ValueError):
    pass


def _practice(ctx: AppContext) -> None:
    if not ctx.org or ctx.org.get("kind") != "sample":
        raise PracticeOnly("Try to tamper exists only in practice companies; a real company's audit log is never edited")


def _currency(obj: Any) -> str | None:
    if isinstance(obj, dict):
        if isinstance(obj.get("currency"), str):
            return obj["currency"]
        for v in obj.values():
            found = _currency(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _currency(v)
            if found:
                return found
    return None


def _bump(obj: Any) -> tuple[int, int] | None:
    """Raise the first amount in the event's detail, in place. Returns (from, to)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "amount_minor" and isinstance(v, int) and not isinstance(v, bool):
                obj[k] = v + 100_000
                return v, obj[k]
            found = _bump(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _bump(v)
            if found:
                return found
    return None


def status(ctx: AppContext) -> dict[str, Any]:
    _practice(ctx)
    with ctx.conn() as conn:
        return {"changed": db.get_setting(conn, SETTING, None), "chain": audit.verify_chain(conn)}


def tamper(ctx: AppContext) -> dict[str, Any]:
    _practice(ctx)
    with ctx.conn() as conn, db.transaction(conn):
        if db.get_setting(conn, SETTING, None):
            raise TamperError("one audit event is already changed; restore it first")
        if not audit.verify_chain(conn)["ok"]:
            raise TamperError("the log is already broken")
        for e in db.rows(conn, "SELECT id, action, detail FROM audit_events WHERE detail LIKE '%amount_minor%' ORDER BY id DESC LIMIT 200"):
            detail = json.loads(e["detail"])
            found = _bump(detail)
            if found:
                break
        else:
            raise TamperError("there is no event with an amount to change yet; run the first practice step")
        changed = json.dumps(detail, sort_keys=True)
        conn.execute("UPDATE audit_events SET detail = ? WHERE id = ?", (changed, e["id"]))
        record = {"id": e["id"], "action": e["action"], "field": "amount_minor", "from": found[0], "to": found[1],
                  "currency": _currency(json.loads(e["detail"])),
                  "original": e["detail"], "changed": changed}
        db.set_setting(conn, SETTING, record)
        chain = audit.verify_chain(conn)
    return {"changed": record, "chain": chain}


def undo(conn) -> dict[str, Any] | None:
    """Put the original text back if the demo's change is still there. No audit event; the caller decides."""
    record = db.get_setting(conn, SETTING, None)
    if not record:
        return None
    row = db.row(conn, "SELECT detail FROM audit_events WHERE id = ?", (record["id"],))
    if row and row["detail"] == record["changed"]:
        conn.execute("UPDATE audit_events SET detail = ? WHERE id = ?", (record["original"], record["id"]))
    conn.execute("DELETE FROM settings WHERE key = ?", (SETTING,))
    return record


def restore(ctx: AppContext, actor: str) -> dict[str, Any]:
    _practice(ctx)
    with ctx.conn() as conn, db.transaction(conn):
        record = undo(conn)
        chain = audit.verify_chain(conn)
        if record and chain["ok"]:
            audit.record(conn, iso(ctx.clock.now()), actor, "practice.tamper_tried", "audit_event", str(record["id"]),
                         {"event": record["id"], "event_action": record["action"], "field": record["field"],
                          "changed_from": record["from"], "changed_to": record["to"], "caught_at_event": record["id"]})
            chain = audit.verify_chain(conn)
    return {"restored": record is not None, "chain": chain}
