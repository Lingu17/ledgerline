"""Malformed field types are refused with 422 before they reach the database or the key decoder,
and a refused request changes nothing."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ledgerline.api.app import create_app
from ledgerline.config import load_settings

from .conftest import signup

CUSTOMER = {"name": "Typed Ltd", "country": "GB", "payer_names": ["TYPED LTD"], "refund_beneficiary": "Typed Ltd GB account"}
INVOICE = {"customer_id": "CUST-ACME", "currency": "USD", "amount": "120.00", "due_date": "2026-12-01", "description": "Typed"}


@pytest.fixture()
def client(tmp_path):
    app = create_app(load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path / "d"), "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
                                    "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": "", "ANTHROPIC_API_KEY": ""}))
    c = TestClient(app, raise_server_exceptions=False)
    signup(c, email="typed@deploy.test", start_with="sample")
    return c


def _state(c):
    return c.get("/api/customers").json(), c.get("/api/invoices").json()


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/invoices", {**INVOICE, "customer_id": {}}),
    ("post", "/api/invoices", {**INVOICE, "customer_id": ["CUST-ACME"]}),
    ("post", "/api/invoices", {**INVOICE, "amount": True}),
    ("post", "/api/invoices", {**INVOICE, "description": 5}),
    ("post", "/api/customers", {**CUSTOMER, "agent_public_key": 123}),
    ("post", "/api/customers", {**CUSTOMER, "agent_public_key": {"k": 1}}),
    ("post", "/api/customers", {**CUSTOMER, "payer_names": [1, 2]}),
    ("patch", "/api/customers/CUST-ACME", {"agent_public_key": 123}),
    ("patch", "/api/customers/CUST-ACME", {"name": ["x"]}),
    ("patch", "/api/invoices/INV-2231", {"due_date": 20261201}),
])
def test_wrong_field_types_are_422_and_change_nothing(client, method, path, body):
    before = _state(client)
    r = getattr(client, method)(path, json=body)
    assert r.status_code == 422, r.text
    assert _state(client) == before


def test_valid_requests_still_work(client):
    assert client.post("/api/invoices", json=INVOICE).status_code == 200
    assert client.post("/api/invoices", json={**INVOICE, "amount": 99}).status_code == 200
    assert client.post("/api/customers", json=CUSTOMER).status_code == 200
    assert client.patch("/api/customers/CUST-ACME", json={"agent_public_key": None}).status_code == 200
    # Missing fields keep the domain's own message.
    r = client.post("/api/customers", json={})
    assert r.status_code == 422 and "name must be" in r.json()["detail"]
