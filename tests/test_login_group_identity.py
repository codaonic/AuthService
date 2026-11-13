"""One person, one account per login group -- whatever case they type."""

import pytest

from app.db.models import User
from tests.helpers import create_admin, create_client, create_user, extract_hidden_value

REDIRECT_URI = "https://client.example.com/callback"


async def _login_admin(client, db_session):
    await create_admin(db_session)
    await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})


async def _flow(client, client_id="shop", **extra):
    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "resource": "https://api.example.com",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
            **extra,
        },
    )
    return extract_hidden_value(resp.text, "flow_id")


@pytest.mark.asyncio
async def test_email_case_does_not_make_a_second_account(client, db_session):
    await create_client(db_session, client_id="shop", pool_name="acme")
    await create_user(db_session, email="bo@example.com", client_id="shop")

    flow_id = await _flow(client, screen="signup")
    resp = await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "first_name": "Bo",
            "last_name": "Li",
            "email": "  Bo@Example.COM ",
            "password": "bo-password-123",
            "confirm_password": "bo-password-123",
        },
    )
    assert "already exists" in resp.text


@pytest.mark.asyncio
async def test_login_works_whatever_case_is_typed(client, db_session):
    await create_client(db_session, client_id="shop", pool_name="acme")
    await create_user(db_session, email="bo@example.com", password="bo-password-123", client_id="shop")
    flow_id = await _flow(client)
    resp = await client.post("/login", data={"flow_id": flow_id, "email": "BO@example.com", "password": "bo-password-123"})
    assert resp.status_code == 200 and "Invalid email" not in resp.text


@pytest.mark.asyncio
async def test_joining_a_login_group_with_clashing_accounts_is_refused(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="shop", pool_name="acme")
    await create_client(db_session, client_id="blog", pool_name="solo")
    await create_user(db_session, email="bo@example.com", client_id="shop")
    await create_user(db_session, email="Bo@example.com", client_id="blog")

    resp = await client.post("/admin/api/pools/acme/assign-client", json={"client_id": "blog"})
    assert resp.status_code == 409
    assert "bo@example.com" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_existing_duplicates_fail_closed_instead_of_crashing(client, db_session):
    """Accounts that clashed before the join was guarded: sign-in through a
    third app can't tell whose account it is, so it refuses."""
    await create_client(db_session, client_id="shop", pool_name="acme")
    await create_client(db_session, client_id="blog", pool_name="acme")
    await create_client(db_session, client_id="news", pool_name="acme")
    for app in ("shop", "blog"):
        await create_user(db_session, email="bo@example.com", password="bo-password-123", client_id=app)

    flow_id = await _flow(client, client_id="news")
    resp = await client.post("/login", data={"flow_id": flow_id, "email": "bo@example.com", "password": "bo-password-123"})
    assert resp.status_code == 401

    # Through an app one of them registered with, theirs is unambiguous.
    flow_id = await _flow(client, client_id="shop")
    resp = await client.post("/login", data={"flow_id": flow_id, "email": "bo@example.com", "password": "bo-password-123"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_cannot_add_a_second_account_elsewhere_in_the_group(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="shop", pool_name="acme")
    await create_client(db_session, client_id="blog", pool_name="acme")
    await create_user(db_session, email="bo@example.com", client_id="shop")

    body = {
        "client_id": "blog",
        "email": "BO@example.com",
        "password": "long-enough-pass-1",
        "confirm_password": "long-enough-pass-1",
    }
    assert (await client.post("/admin/api/users", json=body)).status_code == 400

    body["email"] = "  New@Example.com "
    created = await client.post("/admin/api/users", json=body)
    assert created.json()["email"] == "new@example.com"
    assert isinstance(created.json()["id"], str) and User
