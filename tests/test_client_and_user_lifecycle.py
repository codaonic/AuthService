import pytest

from tests.helpers import create_admin, create_client, create_resource, create_user, extract_hidden_value

REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"


async def _login_admin(client, db_session, **kwargs):
    admin = await create_admin(db_session, **kwargs)
    await client.post(
        "/admin/api/login", json={"email": admin.email, "password": kwargs.get("password", "admin-password!")}
    )
    return admin


# --- Disabling a client blocks it everywhere ---


@pytest.mark.asyncio
async def test_disabled_client_cannot_start_authorize(client, db_session):
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,))
    await create_resource(db_session, resource_id=RESOURCE)
    await _login_admin(db_session=db_session, client=client)

    resp = await client.post("/admin/api/clients/test-client/toggle-enabled")
    assert resp.status_code == 200

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
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_can_toggle_client_enabled_from_ui(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="test-client")

    resp = await client.get("/admin/api/clients")
    assert next(c for c in resp.json() if c["client_id"] == "test-client")["enabled"] is True

    await client.post("/admin/api/clients/test-client/toggle-enabled")
    resp = await client.get("/admin/api/clients")
    assert next(c for c in resp.json() if c["client_id"] == "test-client")["enabled"] is False

    await client.post("/admin/api/clients/test-client/toggle-enabled")
    resp = await client.get("/admin/api/clients")
    assert next(c for c in resp.json() if c["client_id"] == "test-client")["enabled"] is True


# --- Disabling a user blocks login and kills existing access ---


async def _get_flow_id(client, db_session):
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
    return extract_hidden_value(resp.text, "flow_id")


@pytest.mark.asyncio
async def test_disabled_user_cannot_log_in(client, db_session):
    await create_user(db_session, email="alice@example.com", password="pw-12345!")
    flow_id = await _get_flow_id(client, db_session)

    from sqlalchemy import select

    from app.db.models import User

    result = await db_session.execute(select(User))
    user = result.scalars().first()
    user.status = "disabled"
    await db_session.commit()

    resp = await client.post(
        "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "pw-12345!"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_disabling_user_revokes_refresh_tokens(client, db_session, redis_client):
    await create_user(db_session, email="alice@example.com", password="pw-12345!")
    await _login_admin(client, db_session)

    from sqlalchemy import select

    from app.db.models import User
    from app.oidc.refresh import issue_refresh_token

    result = await db_session.execute(select(User))
    user = result.scalars().first()
    refresh_token = await issue_refresh_token(
        db_session, redis_client, str(user.id), "test-client", RESOURCE, scope="profile"
    )

    resp = await client.post(f"/admin/api/users/{user.id}/toggle-status")
    assert resp.status_code == 200

    key = f"refresh:{__import__('hashlib').sha256(refresh_token.encode()).hexdigest()}"
    assert await redis_client.exists(key) == 0


@pytest.mark.asyncio
async def test_admin_sign_out_user_revokes_sessions(client, db_session, redis_client):
    await create_user(db_session, email="alice@example.com", password="pw-12345!")
    flow_id = await _get_flow_id(client, db_session)
    resp = await client.post(
        "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "pw-12345!"}
    )
    assert resp.status_code == 200  # consent screen, session cookie set

    session_cookie = client.cookies.get("auth_session")
    assert session_cookie is not None

    await _login_admin(client, db_session)

    from sqlalchemy import select

    from app.db.models import User

    result = await db_session.execute(select(User))
    user = result.scalars().first()

    resp = await client.post(f"/admin/api/users/{user.id}/sign-out")
    assert resp.status_code == 204

    assert await redis_client.exists(f"session:{session_cookie}") == 0


@pytest.mark.asyncio
async def test_admin_can_toggle_user_status_from_ui(client, db_session):
    await create_user(db_session, email="alice@example.com", password="pw-12345!")
    await _login_admin(client, db_session)

    from sqlalchemy import select

    from app.db.models import User

    result = await db_session.execute(select(User))
    user = result.scalars().first()

    resp = await client.get("/admin/api/users")
    assert next(u for u in resp.json() if u["email"] == "alice@example.com")["status"] == "active"

    await client.post(f"/admin/api/users/{user.id}/toggle-status")
    resp = await client.get("/admin/api/users")
    assert next(u for u in resp.json() if u["email"] == "alice@example.com")["status"] == "disabled"
