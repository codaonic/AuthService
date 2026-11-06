"""Account security fixes: a password change signs apps out, adding a passkey
needs the password, and a changed email has to be verified again."""

import pytest
from sqlalchemy import select

from app.db.models import User
from app.oidc.refresh import issue_refresh_token, refresh_token_owner
from tests.helpers import create_admin, create_client, create_resource, create_user, extract_hidden_value

REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"
EMAIL = "alice@example.com"
PASSWORD = "pw-12345678!"


async def _signed_in(client, db_session):
    """Alice, signed in to the account page through an app."""
    user = await create_user(db_session, email=EMAIL, password=PASSWORD)
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,))
    await create_resource(db_session, resource_id=RESOURCE)
    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "test-client",
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
    )
    flow_id = extract_hidden_value(resp.text, "flow_id")
    resp = await client.post("/login", data={"flow_id": flow_id, "email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 200
    return user


@pytest.mark.asyncio
async def test_changing_your_password_signs_your_apps_out(client, db_session, redis_client):
    user = await _signed_in(client, db_session)
    app_token = await issue_refresh_token(db_session, redis_client, str(user.id), "test-client", RESOURCE)
    assert await refresh_token_owner(redis_client, app_token, "test-client") == str(user.id)

    resp = await client.post(
        "/account/password",
        data={"current_password": PASSWORD, "new_password": "new-pw-1234567", "confirm_password": "new-pw-1234567"},
    )
    assert resp.status_code == 200
    assert "signed out of your other devices and apps" in resp.text
    assert await refresh_token_owner(redis_client, app_token, "test-client") is None


@pytest.mark.asyncio
async def test_adding_a_passkey_needs_the_current_password(client, db_session):
    await _signed_in(client, db_session)

    assert (await client.post("/account/webauthn/register/options")).status_code == 403
    wrong = await client.post("/account/webauthn/register/options", data={"current_password": "not-it"})
    assert wrong.status_code == 403 and "incorrect" in wrong.json()["detail"]

    right = await client.post("/account/webauthn/register/options", data={"current_password": PASSWORD})
    assert right.status_code == 200
    assert "challenge" in right.json()


@pytest.mark.asyncio
async def test_passkey_password_guesses_count_toward_the_lockout(client, db_session, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("LOGIN_MAX_FAILURES", "3")
    get_settings.cache_clear()
    await _signed_in(client, db_session)

    for _ in range(3):
        await client.post("/account/webauthn/register/options", data={"current_password": "guess"})
    locked = await client.post("/account/webauthn/register/options", data={"current_password": PASSWORD})
    assert locked.status_code == 429


@pytest.mark.asyncio
async def test_admin_changing_an_email_makes_it_unverified(client, db_session):
    await create_admin(db_session, email="admin@example.com", password="admin-password!")
    await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})
    await create_client(db_session, client_id="test-client")
    user = await create_user(db_session, email=EMAIL)
    user.email_verified = True
    await db_session.commit()

    # Saving other details keeps the email verified...
    resp = await client.patch(f"/admin/api/users/{user.id}", json={"email": EMAIL, "first_name": "Alice"})
    assert resp.status_code == 200 and resp.json()["email_verified"] is True

    # ...a different address has to be confirmed again.
    resp = await client.patch(f"/admin/api/users/{user.id}", json={"email": "alice@new.example"})
    assert resp.json()["email_verified"] is False
    stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert stored.email_verified is False
