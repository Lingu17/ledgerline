from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledgerline import db  # noqa: E402
from ledgerline.api.app import build_context, create_app  # noqa: E402
from ledgerline.config import load_settings  # noqa: E402
from ledgerline.demo import run_step  # noqa: E402

OP = {"X-Ledgerline-Operator": "tester"}


@pytest.fixture
def settings(tmp_path):
    return load_settings({
        "LEDGERLINE_DATA_DIR": str(tmp_path),
        "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
        "LEDGERLINE_PROVIDER": "local",
        "LEDGERLINE_SAMPLE_WORKSPACE": "0",
        "LEDGERLINE_OPERATOR_TOKEN": "",
        "ANTHROPIC_API_KEY": "",
        "AIRWALLEX_CLIENT_ID": "",
        "AIRWALLEX_API_KEY": "",
        "AIRWALLEX_WEBHOOK_SECRET": "",
    })


@pytest.fixture
def ctx(settings):
    c = build_context(settings)
    run_step(c, "seed", "tester")
    return c


def run_to(ctx, last: str) -> None:
    for step in ["deposits", "links", "agents", "treasury", "approve", "bank_sent", "bank_paid"]:
        run_step(ctx, step, "tester")
        if step == last:
            return


PASSWORD = "Correct-Horse-42-battery"


def signup(client, email="owner@northbeam.test", org="Northbeam Software", start_with="sample"):
    r = client.post("/api/auth/signup", json={"email": email, "name": email.split("@")[0], "password": PASSWORD,
                                              "organization_name": org, "start_with": start_with})
    assert r.status_code == 200, r.text
    me = r.json()
    client.headers["X-CSRF-Token"] = me["csrf_token"]
    client.org_id = me["organization"]["id"]
    org_row = client.app.state.control.org(client.org_id)
    client.webhook_secret = org_row["webhook_secret_local"]
    client.webhook_url = f"/api/webhooks/airwallex/{client.org_id}"
    return me


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    """Signed-in owner of a sample organization (seeded customers and invoices, no deposits yet)."""
    from fastapi.testclient import TestClient

    c = TestClient(app)
    signup(c)
    return c


def new_client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def q(ctx, sql, params=()):
    with ctx.conn() as conn:
        return db.rows(conn, sql, params)


def one(ctx, sql, params=()):
    with ctx.conn() as conn:
        return db.row(conn, sql, params)
