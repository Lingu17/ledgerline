"""A company connects its own Airwallex account: checked first, encrypted, isolated, never returned. CSV onboarding."""
import pytest

from ledgerline import connections
from ledgerline.providers import airwallex
from ledgerline.providers.base import ProviderError

from .conftest import signup

KEY = "very-secret-api-key"
READY = {"global_accounts": [{"id": "ga_eur", "supported_currencies": ["EUR"]}, {"id": "ga_multi", "supported_currencies": ["USD", "GBP"]}],
         "balances": [{"currency": "EUR", "available_amount": 10}]}


@pytest.fixture
def real(app):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    signup(c, email="owner@real.test", org="Real Company", start_with="empty")
    return c


@pytest.fixture
def accepted(monkeypatch):
    monkeypatch.setattr(airwallex.AirwallexSandbox, "readiness", lambda self: READY)


BODY = {"client_id": "client-123456", "api_key": KEY, "webhook_secret": "whsec-12345678"}


def test_connect_saves_only_encrypted_and_never_returns_the_key(real, app, accepted):
    r = real.post("/api/integrations/airwallex/connect", json=BODY)
    assert r.status_code == 200, r.text
    assert r.json()["receiving_accounts"] == {"EUR": "ga_eur"}
    assert sorted(r.json()["missing_currencies"]) == ["GBP", "USD"]
    row = app.state.control.org(real.org_id)
    assert KEY not in row["airwallex_credentials_enc"] and row["bank_mode"] == "airwallex_sandbox"
    org = real.get("/api/organization")
    assert org.json()["airwallex_connected"] is True and KEY not in org.text
    assert KEY not in str(org.json()["control_audit"])
    assert real.get("/api/status").json()["bank"]["mode"] == "airwallex_sandbox"


def test_account_balance_becomes_opening_cash_once(real, app, accepted, monkeypatch):
    real.post("/api/integrations/airwallex/connect", json=BODY)
    eur = lambda: next(w for w in real.get("/api/overview").json()["wallets"] if w["currency"] == "EUR")  # noqa: E731
    assert eur()["cash"] == 1000
    real.post("/api/integrations/airwallex/connect", json=BODY)  # new keys, same account
    assert eur()["cash"] == 1000
    other = {**READY, "global_accounts": [{"id": "ga_other", "supported_currencies": ["EUR"]}]}
    monkeypatch.setattr(airwallex.AirwallexSandbox, "readiness", lambda self: other)
    assert real.post("/api/integrations/airwallex/connect", json=BODY).status_code == 409


def test_bad_keys_save_nothing(real, app, monkeypatch):
    def refuse(self):
        raise ProviderError(f"refused {KEY}")

    monkeypatch.setattr(airwallex.AirwallexSandbox, "readiness", refuse)
    r = real.post("/api/integrations/airwallex/connect", json=BODY)
    assert r.status_code == 422 and KEY not in r.text
    assert app.state.control.org(real.org_id)["airwallex_credentials_enc"] is None


def test_ciphertext_cannot_be_moved_to_another_organization(settings):
    blob = connections.seal(settings, "org_aaaaaaaaaaaa", "id", KEY)
    assert connections.unseal(settings, "org_aaaaaaaaaaaa", blob) == ("id", KEY)
    with pytest.raises(connections.ConnectionError_):
        connections.unseal(settings, "org_bbbbbbbbbbbb", blob)


def test_practice_company_cannot_connect(client, accepted):
    assert client.post("/api/integrations/airwallex/connect", json=BODY).status_code == 409


def test_connect_refused_after_money_activity(real, accepted):
    real.post("/api/treasury/opening-balance", json={"currency": "EUR", "amount": "100"})
    assert real.post("/api/integrations/airwallex/connect", json=BODY).status_code == 409


def test_other_organization_does_not_inherit_the_connection(real, app, accepted):
    from fastapi.testclient import TestClient

    real.post("/api/integrations/airwallex/connect", json=BODY)
    other = TestClient(app)
    signup(other, email="owner@other.test", org="Other Company", start_with="empty")
    assert other.get("/api/status").json()["bank"]["mode"] == "local"
    assert other.get("/api/integrations/sandbox/deposits").status_code == 403


def test_disconnect_returns_to_local(real, app, accepted):
    real.post("/api/integrations/airwallex/connect", json=BODY)
    assert real.post("/api/integrations/airwallex/disconnect").status_code == 200
    assert app.state.control.org(real.org_id)["airwallex_credentials_enc"] is None
    assert real.get("/api/status").json()["bank"]["mode"] == "local"


def test_operator_cannot_connect(real, app, accepted):
    from .test_saas import _invite_and_join

    op = _invite_and_join(real, app, "op@real.test", "operator")
    assert op.post("/api/integrations/airwallex/connect", json=BODY).status_code == 403


def test_csv_onboarding_and_checklist(real):
    assert real.get("/api/setup").json()["show"] is True
    r = real.post("/api/customers/import", json={"csv": "name,country,payer_names,refund_beneficiary\nOrchard Tea,gb,ORCHARD TEA|ORCHARD LTD,Orchard GB\nBad,GBR,X Y,Z Z"}).json()
    assert (r["created"], r["errors"]) == (1, 1)
    r = real.post("/api/invoices/import", json={"csv": "customer,currency,amount,due_date,description\nOrchard Tea,GBP,1250.00,2030-01-01,Tea\nNobody,GBP,1,2030-01-01,x"}).json()
    assert (r["created"], r["errors"]) == (1, 1)
    r = real.post("/api/treasury/obligations/import", json={"csv": "payee,currency,amount,due_date,priority,defer_until,description\nPayroll,EUR,900,2030-01-01,critical,,Staff\nAgency,EUR,100,2030-01-01,flexible,2030-02-01,Design"}).json()
    assert (r["created"], r["errors"]) == (2, 0)
    done = {s["id"]: s["done"] for s in real.get("/api/setup").json()["steps"]}
    assert done["customers"] and done["invoices"] and done["bills"] and not done["bank"]
    assert real.post("/api/customers/import", json={"csv": "wrong,header\n1,2"}).status_code in (409, 422)


def test_second_approver_ticks_only_when_someone_who_can_approve_has_joined(real, app):
    from .test_saas import _invite_and_join

    step = lambda: {s["id"]: s["done"] for s in real.get("/api/setup").json()["steps"]}["approver"]  # noqa: E731
    real.post("/api/team/invitations", json={"email": "pending@real.test", "role": "operator"})
    assert step() is False  # an invitation alone is not a second approver
    _invite_and_join(real, app, "viewer@real.test", "viewer")
    assert step() is False  # a viewer cannot approve
    _invite_and_join(real, app, "op2@real.test", "operator")
    assert step() is True
