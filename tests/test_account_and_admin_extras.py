import pytest

from app.db.models import Client
from app.db.pools import get_or_create_pool
from tests.helpers import create_admin, create_client, create_resource, create_user, extract_hidden_value

REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"


async def _login_admin(client, db_session, **kwargs):
    admin = await create_admin(db_session, **kwargs)
    await client.post(
        "/admin/api/login", json={"email": admin.email, "password": kwargs.get("password", "admin-password!")}
    )
    return admin


async def _login_end_user(client, db_session, email="alice@example.com", password="pw-12345!"):
    await create_user(db_session, email=email, password=password)
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
    resp = await client.post("/login", data={"flow_id": flow_id, "email": email, "password": password})
    assert resp.status_code == 200


# --- mTLS thumbprint from the admin UI ---


@pytest.mark.asyncio
async def test_admin_can_set_and_view_mtls_thumbprint(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="svc-client", client_type="confidential", grant_types=("client_credentials",))

    resp = await client.post("/admin/api/clients/svc-client/mtls", json={"thumbprint": "ab:cd:ef"})
    assert resp.status_code == 200
    assert resp.json()["mtls_cert_thumbprint"] == "AB:CD:EF"

    resp = await client.get("/admin/api/clients")
    assert resp.status_code == 200
    assert any(c["mtls_cert_thumbprint"] == "AB:CD:EF" for c in resp.json())


# --- CIMD clients are visually distinguished, not editable for mTLS/signup ---


@pytest.mark.asyncio
async def test_cimd_client_shown_with_badge_and_no_mtls_form(client, db_session):
    await _login_admin(client, db_session)
    pool = await get_or_create_pool(db_session, "default")
    db_session.add(
        Client(
            user_pool_id=pool.id,
            client_id="https://mcp.example.com/.well-known/client-id",
            client_type="public",
            registration_method="cimd",
        )
    )
    await db_session.commit()

    resp = await client.get("/admin/api/clients")
    assert resp.status_code == 200
    cimd_client = next(c for c in resp.json() if c["registration_method"] == "cimd")
    assert cimd_client["client_id"] == "https://mcp.example.com/.well-known/client-id"


# --- Activity log ---


@pytest.mark.asyncio
async def test_audit_log_requires_login(client):
    resp = await client.get("/admin/api/audit")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_audit_log_shows_recent_events(client, db_session):
    await create_admin(db_session, email="admin@example.com", password="admin-password!")
    await client.post(
        "/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"}
    )

    resp = await client.get("/admin/api/audit")
    assert resp.status_code == 200
    assert any(e["event"] == "admin_login_success" for e in resp.json())


# --- End-user account: password change ---


@pytest.mark.asyncio
async def test_account_password_change(client, db_session):
    await _login_end_user(client, db_session, password="original-pw!")

    resp = await client.post(
        "/account/password",
        data={
            "current_password": "original-pw!",
            "new_password": "brand-new-pw!",
            "confirm_password": "brand-new-pw!",
        },
    )
    assert resp.status_code == 200
    assert "Password updated" in resp.text


@pytest.mark.asyncio
async def test_account_password_change_wrong_current(client, db_session):
    await _login_end_user(client, db_session, password="original-pw!")

    resp = await client.post(
        "/account/password",
        data={
            "current_password": "totally-wrong",
            "new_password": "brand-new-pw!",
            "confirm_password": "brand-new-pw!",
        },
    )
    assert resp.status_code == 400
    assert "incorrect" in resp.text


# --- End-user account: sessions ---


@pytest.mark.asyncio
async def test_account_shows_current_session_and_can_revoke_it(client, db_session, redis_client):
    await _login_end_user(client, db_session)

    resp = await client.get("/account")
    assert resp.status_code == 200
    assert "This device" in resp.text

    from sqlalchemy import select

    from app.auth.sessions import list_sessions_for_user
    from app.db.models import User

    result = await db_session.execute(select(User))
    user = result.scalars().first()

    sessions = await list_sessions_for_user(redis_client, str(user.id))
    assert len(sessions) == 1

    resp = await client.post(f"/account/sessions/{sessions[0]['id']}/revoke")
    assert resp.status_code == 303

    resp = await client.get("/account")
    assert "You're not signed in" in resp.text
