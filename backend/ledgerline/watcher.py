"""Background checks for connected accounts, so nobody has to remember to click.

- Open payment links are asked whether they were paid; a paid one is booked by the same code as the button.
- Every few rounds, deposits are listed as the fallback for missed webhooks.
- A payment still waiting on a payer's agent is asked about again.

Both are idempotent on the provider's id. Nothing here sends money, creates a link or retries a submission.
One organization's failure never stops the others.
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta
from typing import Any

from . import judge_demo, agent_loop, db, early_pay, payment_links, sandbox_receipts
from .clock import iso

log = logging.getLogger("ledgerline.watcher")

ACTOR = "system:watcher"
LINK_MAX_AGE = timedelta(days=30)
DEPOSITS_EVERY = 5


def _check_links(ctx) -> None:
    cutoff = iso(ctx.clock.now() - LINK_MAX_AGE)
    with ctx.conn() as conn:
        offers = db.rows(conn, "SELECT id FROM early_pay_offers WHERE status = 'open' AND provider_id IS NOT NULL AND created_at >= ?", (cutoff,))
        links = db.rows(conn, "SELECT id FROM payment_links WHERE status = 'sandbox_created' AND provider_id IS NOT NULL AND created_at >= ?", (cutoff,))
    for o in offers:
        early_pay.check(ctx, o["id"], ACTOR)
    for link in links:
        payment_links.check(ctx, link["id"], ACTOR)
    if offers or links:
        with ctx.conn() as conn, db.transaction(conn):
            db.set_setting(conn, "links_last_checked", iso(ctx.clock.now()))


def sweep(orgs: Any, control: Any, *, deposits: bool = False) -> int:
    """One round over every connected organization. Returns how many organizations were checked."""
    checked = 0
    for org_id in control.all_org_ids():
        org = control.org(org_id)
        if not org or org.get("bank_mode") != "airwallex_sandbox":
            continue
        try:
            ctx = orgs.get(org_id)
            _check_links(ctx)
            agent_loop.ask_pending(ctx)
            if deposits and ctx.settings.airwallex_global_account_ids:
                sandbox_receipts.discover(ctx, ACTOR, since=org["created_at"])
            checked += 1
        except Exception as exc:  # noqa: BLE001 - a provider or configuration problem in one organization must not stop the rest
            log.warning("watcher: %s skipped: %s", org_id, type(exc).__name__)
    return checked


def start(app: Any, seconds: int) -> threading.Thread | None:
    if seconds <= 0:
        return None

    def run() -> None:
        stop = threading.Event()
        round_no = 0
        while not stop.wait(seconds):
            round_no += 1
            try:
                sweep(app.state.orgs, app.state.control, deposits=round_no % DEPOSITS_EVERY == 0)
            except Exception as exc:  # noqa: BLE001 - the loop outlives a bad round
                log.warning("watcher: round failed: %s", type(exc).__name__)
            try:
                judge_demo.cleanup(app)  # demo companies older than 48 hours
            except Exception as exc:  # noqa: BLE001
                log.warning("watcher: demo cleanup failed: %s", type(exc).__name__)

    thread = threading.Thread(target=run, name="ledgerline-watcher", daemon=True)
    thread.start()
    return thread
