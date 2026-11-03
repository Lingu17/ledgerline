"""Limits on new accounts and organizations: per client address, and for the whole server per day."""
import json
from datetime import timedelta

from fastapi.testclient import TestClient

from ledgerline.api.app import create_app
from ledgerline.clock import Clock

from .conftest import PASSWORD

n = iter(range(10_000))


def make_app(settings, limits=(3, 5, 100), hops=0):
    settings.signup_limits = limits
    settings.trusted_proxy_hops = hops
    clock = Clock()
    return create_app(settings, clock), clock


def sign_up(app, headers=None, start_with="sample"):
    c = TestClient(app)
    i = next(n)
    return c.post("/api/auth/signup", headers=headers or {}, json={"email": f"user{i}@limits.test", "name": "Judge", "password": PASSWORD,
                                                                  "organization_name": f"Company {i}", "start_with": start_with}), c


def test_per_address_hourly_limit_with_a_clear_429(settings):
    app, clock = make_app(settings)
    for _ in range(3):
        assert sign_up(app)[0].status_code == 200
    r, _ = sign_up(app)
    assert r.status_code == 429 and "last hour" in r.json()["detail"] and r.headers["retry-after"] == "3600"
    clock.advance(timedelta(minutes=61))
    assert sign_up(app)[0].status_code == 200


def test_new_organizations_count_too(settings):
    app, _ = make_app(settings)
    r, c = sign_up(app)
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert c.post("/api/organizations", json={"name": "Second", "start_with": "empty"}).status_code == 200
    assert c.post("/api/organizations", json={"name": "Third", "start_with": "empty"}).status_code == 200
    r = c.post("/api/organizations", json={"name": "Fourth", "start_with": "empty"})
    assert r.status_code == 429


def test_per_address_daily_limit(settings):
    app, clock = make_app(settings, limits=(3, 5, 100))
    for _ in range(3):
        assert sign_up(app)[0].status_code == 200
    clock.advance(timedelta(minutes=61))
    for _ in range(2):
        assert sign_up(app)[0].status_code == 200
    clock.advance(timedelta(minutes=61))
    r, _ = sign_up(app)
    assert r.status_code == 429 and "today" in r.json()["detail"]


def test_server_wide_daily_cap(settings):
    app, _ = make_app(settings, limits=(100, 100, 2), hops=1)
    assert sign_up(app, {"x-forwarded-for": "203.0.113.1"})[0].status_code == 200
    assert sign_up(app, {"x-forwarded-for": "203.0.113.2"})[0].status_code == 200
    r, _ = sign_up(app, {"x-forwarded-for": "203.0.113.3"})
    assert r.status_code == 429 and "this server has reached today's limit" in r.json()["detail"]


def test_a_spoofed_forwarded_for_changes_nothing(settings):
    # Behind one trusted proxy, only the address the proxy appended counts; whatever the client put in front is ignored.
    app, _ = make_app(settings, hops=1)
    for i in range(3):
        assert sign_up(app, {"x-forwarded-for": f"10.9.9.{i}, 198.51.100.7"})[0].status_code == 200
    r, _ = sign_up(app, {"x-forwarded-for": "10.9.9.99, 198.51.100.7"})
    assert r.status_code == 429
    # With no trusted proxy, the header is ignored entirely and the socket peer is counted.
    app2, _ = make_app(settings.__class__(**{**settings.__dict__}), hops=0)
    for i in range(3):
        assert sign_up(app2, {"x-forwarded-for": f"192.0.2.{i}"})[0].status_code == 200
    assert sign_up(app2, {"x-forwarded-for": "192.0.2.200"})[0].status_code == 429


def test_ipv6_addresses_in_one_slash_64_count_as_one_client(settings):
    app, _ = make_app(settings, hops=1)
    for i in range(3):
        assert sign_up(app, {"x-forwarded-for": f"2001:db8:1:2::{i + 1}"})[0].status_code == 200
    assert sign_up(app, {"x-forwarded-for": "2001:db8:1:2:ffff::9"})[0].status_code == 429
    assert sign_up(app, {"x-forwarded-for": "2001:db8:1:3::1"})[0].status_code == 200  # another /64


def test_old_rows_are_pruned(settings):
    app, clock = make_app(settings)
    sign_up(app)
    clock.advance(timedelta(days=3))
    sign_up(app)
    with app.state.control.conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM creations").fetchone()[0] == 1


def test_the_address_is_recorded_on_sign_up_and_new_organization(settings):
    app, _ = make_app(settings, hops=1)
    r, c = sign_up(app, {"x-forwarded-for": "198.51.100.23"})
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    c.post("/api/organizations", json={"name": "Second", "start_with": "empty"}, headers={"x-forwarded-for": "198.51.100.23"})
    with app.state.control.conn() as conn:
        rows = conn.execute("SELECT action, detail FROM control_audit WHERE action IN ('user.signup', 'org.created')").fetchall()
    assert {a: json.loads(d)["ip"] for a, d in rows} == {"user.signup": "198.51.100.23", "org.created": "198.51.100.23"}


def test_ten_judges_behind_one_office_address_get_in_with_the_default_limits(settings):
    settings.trusted_proxy_hops = 1
    app = create_app(settings)
    for _ in range(10):
        assert sign_up(app, {"x-forwarded-for": "198.51.100.50"})[0].status_code == 200
