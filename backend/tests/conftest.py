from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Optional: backend/.env.test (gitignored) may hold LEDGERLINE_TEST_DATABASE_URL so the secret is never typed on a command line.
_env_test = Path(__file__).resolve().parent.parent / ".env.test"
if _env_test.is_file():
    import os as _os

    for _line in _env_test.read_text(encoding="utf-8").splitlines():
        if _line.startswith("LEDGERLINE_TEST_DATABASE_URL="):
            _os.environ.setdefault("LEDGERLINE_TEST_DATABASE_URL", _line.split("=", 1)[1].strip())

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


@pytest.fixture(scope="session", autouse=True)
def _drop_postgres_test_schemas():
    """With LEDGERLINE_TEST_DATABASE_URL set, tests create throwaway schemas named x<8 hex>_...; drop them afterwards."""
    yield
    import os

    url = os.environ.get("LEDGERLINE_TEST_DATABASE_URL")
    if not url:
        return
    import psycopg

    from ledgerline import pg

    pg.close_all()
    with psycopg.connect(url, autocommit=True) as c:
        names = [r[0] for r in c.execute(r"SELECT nspname FROM pg_namespace WHERE nspname ~ '^x[0-9a-f]{8}_'").fetchall()]
        for n in names:
            c.execute(f'DROP SCHEMA "{n}" CASCADE')
