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


# --- Client branding renders on the login page ---


@pytest.mark.asyncio
async def test_client_branding_renders_on_login_page(client, db_session):
    await create_client(
        db_session,
        client_id="branded-client",
        redirect_uris=(REDIRECT_URI,),
        logo_url="https://acme.example.com/logo.png",
        brand_color="#1d4ed8",
    )
    await create_resource(db_session, resource_id=RESOURCE)

    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "branded-client",
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
    )
    assert resp.status_code == 200
    assert 'src="https://acme.example.com/logo.png"' in resp.text
    assert "--color-primary: #1d4ed8;" in resp.text


@pytest.mark.asyncio
async def test_no_branding_falls_back_to_default_icon(client, db_session):
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
    assert resp.status_code == 200
    assert "<img" not in resp.text
    assert "--color-primary: #1d4ed8;" not in resp.text


# --- restrict_access: per-app allow-list on top of a shared login group ---


async def _authorize_flow_id(client):
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
async def test_restricted_client_rejects_ungranted_user(client, db_session):
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,), restrict_access=True)
    await create_resource(db_session, resource_id=RESOURCE)
    await create_user(db_session, email="alice@example.com", password="pw-12345!")
    flow_id = await _authorize_flow_id(client)

    resp = await client.post(
        "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "pw-12345!"}
    )
    assert resp.status_code == 403
    assert "doesn&#39;t have access" in resp.text or "doesn't have access" in resp.text


@pytest.mark.asyncio
async def test_restricted_client_allows_granted_user(client, db_session):
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,), restrict_access=True)
    await create_resource(db_session, resource_id=RESOURCE)
    user = await create_user(db_session, email="alice@example.com", password="pw-12345!")
    await _login_admin(client, db_session)

    grant_resp = await client.post("/admin/api/clients/test-client/access", json={"user_id": str(user.id)})
    assert grant_resp.status_code == 201

    await client.post("/admin/api/logout")
    flow_id = await _authorize_flow_id(client)
    resp = await client.post(
        "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "pw-12345!"}
    )
    assert resp.status_code == 200
    assert "doesn't have access" not in resp.text


@pytest.mark.asyncio
async def test_signup_through_restricted_client_auto_grants_access(client, db_session):
    await create_client(
        db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,), restrict_access=True, allow_signup=True
    )
    await create_resource(db_session, resource_id=RESOURCE)
    flow_id = await _authorize_flow_id(client)

    resp = await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "email": "newuser@example.com",
            "password": "pw-12345!",
            "confirm_password": "pw-12345!",
        },
    )
    assert resp.status_code == 200
    assert "doesn't have access" not in resp.text

    from sqlalchemy import select

    from app.db.models import ClientAccessGrant, User

    user = (await db_session.execute(select(User).where(User.email == "newuser@example.com"))).scalar_one()
    grant = (
        await db_session.execute(
            select(ClientAccessGrant).where(
                ClientAccessGrant.client_id == "test-client", ClientAccessGrant.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    assert grant is not None


@pytest.mark.asyncio
async def test_revoke_access_blocks_a_previously_granted_user(client, db_session):
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,), restrict_access=True)
    await create_resource(db_session, resource_id=RESOURCE)
    user = await create_user(db_session, email="alice@example.com", password="pw-12345!")
    await _login_admin(client, db_session)
    await client.post("/admin/api/clients/test-client/access", json={"user_id": str(user.id)})

    resp = await client.delete(f"/admin/api/clients/test-client/access/{user.id}")
    assert resp.status_code == 204

    await client.post("/admin/api/logout")
    flow_id = await _authorize_flow_id(client)
    resp = await client.post(
        "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "pw-12345!"}
    )
    assert resp.status_code == 403


# --- Roles: reported by this service, enforced by the application itself ---


async def _run_to_userinfo(client, email="alice@example.com", password="pw-12345!"):
    from tests.helpers import make_pkce_pair

    verifier, challenge = make_pkce_pair()
    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "test-client",
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "profile email",
        },
    )
    flow_id = extract_hidden_value(resp.text, "flow_id")
    await client.post("/login", data={"flow_id": flow_id, "email": email, "password": password})
    consent_resp = await client.post("/consent", data={"flow_id": flow_id, "approve": "true"})

    from urllib.parse import parse_qs, urlparse

    code = parse_qs(urlparse(consent_resp.headers["location"]).query)["code"][0]

    token_resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": "test-client",
            "redirect_uri": REDIRECT_URI,
        },
    )
    access_token = token_resp.json()["access_token"]
    return await client.get("/userinfo", headers={"Authorization": f"Bearer {access_token}"})


@pytest.mark.asyncio
async def test_userinfo_omits_roles_when_client_has_roles_disabled(client, db_session):
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,))
    await create_resource(db_session, resource_id=RESOURCE)
    await create_user(db_session, email="alice@example.com", password="pw-12345!")

    resp = await _run_to_userinfo(client)
    assert resp.status_code == 200
    assert "roles" not in resp.json()


@pytest.mark.asyncio
async def test_userinfo_includes_assigned_roles_when_enabled(client, db_session):
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,))
    await create_resource(db_session, resource_id=RESOURCE)
    user = await create_user(db_session, email="alice@example.com", password="pw-12345!")
    await _login_admin(client, db_session)

    await client.post("/admin/api/clients/test-client/toggle-roles-enabled")
    await client.post("/admin/api/clients/test-client/roles", json={"name": "editor"})
    await client.post(f"/admin/api/users/{user.id}/roles", json={"client_id": "test-client", "role": "editor"})
    await client.post("/admin/api/logout")

    resp = await _run_to_userinfo(client)
    assert resp.status_code == 200
    assert resp.json()["roles"] == ["editor"]


@pytest.mark.asyncio
async def test_signup_role_selection_off_by_default(client, db_session):
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,), allow_signup=True)
    await create_resource(db_session, resource_id=RESOURCE)
    await _login_admin(client, db_session)
    await client.post("/admin/api/clients/test-client/toggle-roles-enabled")
    await client.post("/admin/api/clients/test-client/roles", json={"name": "editor"})
    await client.post("/admin/api/logout")

    flow_id = await _authorize_flow_id(client)
    resp = await client.get("/signup", params={"flow_id": flow_id})
    assert resp.status_code == 200
    assert 'name="role"' not in resp.text


@pytest.mark.asyncio
async def test_signup_can_set_role_when_selection_is_turned_on(client, db_session):
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,), allow_signup=True)
    await create_resource(db_session, resource_id=RESOURCE)
    await _login_admin(client, db_session)
    await client.post("/admin/api/clients/test-client/toggle-roles-enabled")
    await client.post("/admin/api/clients/test-client/toggle-signup-role-selection")
    await client.post("/admin/api/clients/test-client/roles", json={"name": "editor"})
    await client.post("/admin/api/logout")

    flow_id = await _authorize_flow_id(client)
    resp = await client.get("/signup", params={"flow_id": flow_id})
    assert 'name="role"' in resp.text
    assert "editor" in resp.text

    resp = await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "email": "newuser@example.com",
            "password": "pw-12345!",
            "confirm_password": "pw-12345!",
            "role": "editor",
        },
    )
    assert resp.status_code == 200

    from sqlalchemy import select

    from app.db.models import User, UserRoleAssignment

    user = (await db_session.execute(select(User).where(User.email == "newuser@example.com"))).scalar_one()
    assignment = (
        await db_session.execute(select(UserRoleAssignment).where(UserRoleAssignment.user_id == user.id))
    ).scalar_one_or_none()
    assert assignment is not None
    assert assignment.role == "editor"
