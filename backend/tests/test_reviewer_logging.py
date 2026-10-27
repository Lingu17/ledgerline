"""Do not leak one-time invitation credentials into application request logs."""
import logging
from .conftest import PASSWORD, new_client, signup


def test_invitation_token_not_in_application_request_log(client, caplog):
    token = "one-time-invitation-secret-reviewer-probe"
    with caplog.at_level(logging.INFO, logger="ledgerline"):
        response = client.get(f"/api/invitations/{token}")
    assert response.status_code == 404
    lines = [r.getMessage() for r in caplog.records if r.name == "ledgerline"]
    assert lines
    assert all(token not in line for line in lines)
    assert any("/invitations/{token}" in line for line in lines)


def test_existing_user_invitation_cannot_bypass_login_throttle(client, app):
    existing = new_client(app)
    signup(existing, email="existing@review.test", org="Other company", start_with="empty")
    invitation = client.post("/api/team/invitations", json={"email": "existing@review.test", "role": "viewer"})
    token = invitation.json()["invite_path"].split("token=")[1]
    anonymous = new_client(app)
    for _ in range(5):
        assert anonymous.post(f"/api/invitations/{token}/accept", json={"password": "Wrong-password-123"}).status_code == 403
    blocked = anonymous.post(f"/api/invitations/{token}/accept", json={"password": PASSWORD})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert anonymous.post("/api/auth/login", json={"email": "existing@review.test", "password": PASSWORD}).status_code == 429
