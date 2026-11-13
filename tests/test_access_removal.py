"""Taking access away stops new tokens, and roles ride inside the access token."""

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet
from sqlalchemy import select

from app.db.models import Client, ClientAccessGrant, UserRoleAssignment
from app.oidc.refresh import issue_refresh_token
from tests.helpers import create_admin, create_client, create_resource, create_user

RESOURCE = "https://api.example.com"


async def _refresh(client, token):
    return await client.post(
        "/token", data={"grant_type": "refresh_token", "client_id": "shop", "refresh_token": token}
    )


async def _setup(db_session, redis_client, **client_opts):
    roles = client_opts.pop("roles_enabled", False)
    await create_client(db_session, client_id="shop", **client_opts)
    if roles:
        shop = (await db_session.execute(select(Client).where(Client.client_id == "shop"))).scalar_one()
        shop.roles_enabled = True
        await db_session.commit()
    await create_resource(db_session, resource_id=RESOURCE)
    user = await create_user(db_session, email="bo@example.com", client_id="shop")
    token = await issue_refresh_token(db_session, redis_client, str(user.id), "shop", RESOURCE, scope="openid")
    return user, token


@pytest.mark.asyncio
async def test_refresh_stops_when_removed_from_a_restricted_app(client, db_session, redis_client):
    await create_admin(db_session)
    await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})
    user, token = await _setup(db_session, redis_client, restrict_access=True)
    db_session.add(ClientAccessGrant(client_id="shop", user_id=user.id))
    await db_session.commit()

    ok = await _refresh(client, token)
    assert ok.status_code == 200

    assert (await client.delete(f"/admin/api/clients/shop/access/{user.id}")).status_code == 204
    assert (await _refresh(client, ok.json()["refresh_token"])).status_code == 400


@pytest.mark.asyncio
async def test_refresh_stops_when_restriction_is_turned_on_later(client, db_session, redis_client):
    _, token = await _setup(db_session, redis_client)
    shop = (await db_session.execute(select(Client).where(Client.client_id == "shop"))).scalar_one()
    shop.restrict_access = True
    await db_session.commit()
    assert (await _refresh(client, token)).status_code == 400


async def _claims(client, token):
    keys = KeySet.import_key_set((await client.get("/jwks.json")).json())
    return jwt.decode((await _refresh(client, token)).json()["access_token"], keys).claims


@pytest.mark.asyncio
async def test_roles_are_in_the_token_only_when_the_app_uses_roles(client, db_session, redis_client):
    user, token = await _setup(db_session, redis_client, roles_enabled=True)
    db_session.add(UserRoleAssignment(user_id=user.id, client_id="shop", role="owner"))
    await db_session.commit()
    assert (await _claims(client, token))["roles"] == ["owner"]


@pytest.mark.asyncio
async def test_no_roles_claim_when_the_app_has_roles_off(client, db_session, redis_client):
    _, token = await _setup(db_session, redis_client)
    assert "roles" not in await _claims(client, token)


@pytest.mark.asyncio
async def test_replaying_a_used_refresh_token_ends_that_apps_sign_in(client, db_session, redis_client, monkeypatch):
    from app.oidc import refresh

    _, token = await _setup(db_session, redis_client)
    first = await _refresh(client, token)
    assert first.status_code == 200

    monkeypatch.setattr(refresh, "REPLAY_GRACE_SECONDS", 0)
    assert (await _refresh(client, token)).status_code == 400  # the stolen copy
    assert (await _refresh(client, first.json()["refresh_token"])).status_code == 400  # and the real one is out too


@pytest.mark.asyncio
async def test_a_quick_repeat_of_the_same_refresh_is_not_treated_as_theft(client, db_session, redis_client):
    _, token = await _setup(db_session, redis_client)
    first = await _refresh(client, token)
    assert (await _refresh(client, token)).status_code == 400
    assert (await _refresh(client, first.json()["refresh_token"])).status_code == 200


@pytest.mark.asyncio
async def test_a_stranger_failing_logins_cannot_lock_out_the_real_user(redis_client):
    from app.auth.lockout import login_locked, record_login_failure

    for _ in range(10):
        await record_login_failure(redis_client, "bo@example.com", "6.6.6.6")
    assert await login_locked(redis_client, "bo@example.com", "6.6.6.6")
    assert not await login_locked(redis_client, "bo@example.com", "7.7.7.7")

    for _ in range(40):  # a spread-out guessing run still locks the email for everyone
        await record_login_failure(redis_client, "bo@example.com", "8.8.8.8")
    assert await login_locked(redis_client, "bo@example.com", "7.7.7.7")


@pytest.mark.asyncio
async def test_users_the_admin_adds_to_a_restricted_app_can_use_it(client, db_session):
    await create_admin(db_session)
    await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})
    await create_client(db_session, client_id="shop", restrict_access=True)
    body = {
        "client_id": "shop", "email": "new@example.com",
        "password": "long-enough-pass-1", "confirm_password": "long-enough-pass-1",
    }
    resp = await client.post("/admin/api/users", json=body)
    assert resp.status_code in (200, 201), resp.text
    grants = (await db_session.execute(select(ClientAccessGrant))).scalars().all()
    assert len(grants) == 1
