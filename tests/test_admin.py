from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import AdminUser, Client, Resource, User, UserPool
from tests.helpers import create_admin, create_client, create_user


@pytest.mark.asyncio
async def test_admin_spa_served_at_login(client):
    resp = await client.get("/admin/login")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text


@pytest.mark.asyncio
async def test_dashboard_requires_login(client):
    resp = await client.get("/admin/api/dashboard")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_login_wrong_password_rejected(client, db_session):
    await create_admin(db_session, email="admin@example.com", password="correct-password!")

    resp = await client.post(
        "/admin/api/login", json={"email": "admin@example.com", "password": "wrong-password"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_login_and_dashboard(client, db_session):
    await create_admin(db_session, email="admin@example.com", password="correct-password!")

    login_resp = await client.post(
        "/admin/api/login", json={"email": "admin@example.com", "password": "correct-password!"}
    )
    assert login_resp.status_code == 200
    assert login_resp.json()["email"] == "admin@example.com"

    dashboard_resp = await client.get("/admin/api/dashboard")
    assert dashboard_resp.status_code == 200
    assert "counts" in dashboard_resp.json()


async def _login_admin(client, db_session, **kwargs):
    admin = await create_admin(db_session, **kwargs)
    await client.post(
        "/admin/api/login",
        json={"email": admin.email, "password": kwargs.get("password", "admin-password!")},
    )
    return admin


@pytest.mark.asyncio
async def test_create_pool_via_admin(client, db_session):
    await _login_admin(client, db_session)

    resp = await client.post("/admin/api/pools", json={"name": "acme"})
    assert resp.status_code == 201

    result = await db_session.execute(select(UserPool).where(UserPool.name == "acme"))
    assert result.scalar_one() is not None


@pytest.mark.asyncio
async def test_create_resource_via_admin(client, db_session):
    await _login_admin(client, db_session)

    resp = await client.post(
        "/admin/api/resources", json={"resource_id": "https://api.example.com", "name": "API"}
    )
    assert resp.status_code == 201

    result = await db_session.execute(select(Resource).where(Resource.resource_id == "https://api.example.com"))
    assert result.scalar_one() is not None


@pytest.mark.asyncio
async def test_edit_resource_via_admin(client, db_session):
    await _login_admin(client, db_session)
    await client.post(
        "/admin/api/resources", json={"resource_id": "https://api.example.com", "name": "Old API"}
    )
    resp = await client.patch(
        "/admin/api/resources/https://api.example.com",
        json={"name": "New API", "metadata_url": "https://api.example.com/meta"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New API"
    assert resp.json()["metadata_url"] == "https://api.example.com/meta"


@pytest.mark.asyncio
async def test_delete_resource_via_admin(client, db_session):
    await _login_admin(client, db_session)
    await client.post(
        "/admin/api/resources", json={"resource_id": "https://api.example.com", "name": "API"}
    )
    resp = await client.delete("/admin/api/resources/https://api.example.com")
    assert resp.status_code == 204

    result = await db_session.execute(select(Resource).where(Resource.resource_id == "https://api.example.com"))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_toggle_resource_enabled(client, db_session):
    await _login_admin(client, db_session)
    await client.post("/admin/api/resources", json={"resource_id": "https://api.example.com", "name": "API"})

    resp = await client.post("/admin/api/resources/https://api.example.com/toggle-enabled")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    result = await db_session.execute(select(Resource).where(Resource.resource_id == "https://api.example.com"))
    assert result.scalar_one().enabled is False


@pytest.mark.asyncio
async def test_system_endpoints(client, db_session):
    await _login_admin(client, db_session)
    resp = await client.get("/admin/api/system/endpoints")
    assert resp.status_code == 200
    data = resp.json()
    assert "issuer" in data
    assert "authorization_endpoint" in data
    assert "token_endpoint" in data
    assert "jwks_uri" in data
    assert "prm_endpoint" in data


@pytest.mark.asyncio
async def test_create_public_client_via_admin(client, db_session):
    await _login_admin(client, db_session)

    resp = await client.post(
        "/admin/api/clients",
        json={
            "client_id": "acme-web",
            "client_type": "public",
            "redirect_uris": "https://acme.example.com/cb",
            "grant_types": ["authorization_code", "refresh_token"],
            "scope": "profile email",
            "application_type": "web",
            "user_pool": "acme",
            "allow_signup": True,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["client_secret"] is None

    result = await db_session.execute(select(Client).where(Client.client_id == "acme-web"))
    saved = result.scalar_one()
    assert saved.client_type == "public"
    assert saved.allow_signup is True


@pytest.mark.asyncio
async def test_create_confidential_client_shows_secret_once(client, db_session):
    await _login_admin(client, db_session)

    resp = await client.post(
        "/admin/api/clients",
        json={
            "client_id": "acme-service",
            "client_type": "confidential",
            "grant_types": ["client_credentials"],
            "user_pool": "default",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["client_secret"] is not None

    result = await db_session.execute(select(Client).where(Client.client_id == "acme-service"))
    saved = result.scalar_one()
    assert saved.client_secret_hash is not None


@pytest.mark.asyncio
async def test_create_client_with_branding(client, db_session):
    await _login_admin(client, db_session)

    resp = await client.post(
        "/admin/api/clients",
        json={
            "client_id": "acme-branded",
            "client_type": "public",
            "redirect_uris": "https://acme.example.com/cb",
            "logo_url": "https://acme.example.com/logo.png",
            "brand_color": "#1d4ed8",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["logo_url"] == "https://acme.example.com/logo.png"
    assert body["brand_color"] == "#1d4ed8"


@pytest.mark.asyncio
async def test_set_client_branding(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web")

    resp = await client.post(
        "/admin/api/clients/acme-web/branding",
        json={"logo_url": "https://acme.example.com/logo.png", "brand_color": "#1d4ed8"},
    )
    assert resp.status_code == 200
    assert resp.json()["logo_url"] == "https://acme.example.com/logo.png"

    result = await db_session.execute(select(Client).where(Client.client_id == "acme-web"))
    saved = result.scalar_one()
    assert saved.brand_color == "#1d4ed8"

    # Clearing (empty string) unsets it back to None, same as the mTLS field.
    resp = await client.post("/admin/api/clients/acme-web/branding", json={})
    assert resp.json()["logo_url"] is None
    assert resp.json()["brand_color"] is None


@pytest.mark.asyncio
async def test_toggle_client_signup(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web", pool_name="default", allow_signup=True)

    resp = await client.post("/admin/api/clients/acme-web/toggle-signup")
    assert resp.status_code == 200
    assert resp.json()["allow_signup"] is False

    result = await db_session.execute(select(Client).where(Client.client_id == "acme-web"))
    assert result.scalar_one().allow_signup is False


@pytest.mark.asyncio
async def test_toggle_client_restrict_access(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web", pool_name="default")

    resp = await client.post("/admin/api/clients/acme-web/toggle-restrict-access")
    assert resp.status_code == 200
    assert resp.json()["restrict_access"] is True


@pytest.mark.asyncio
async def test_cannot_grant_access_to_a_user_from_a_different_pool(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web", pool_name="acme", restrict_access=True)
    outsider = await create_user(db_session, email="outsider@example.com", pool_name="other-pool")

    resp = await client.post("/admin/api/clients/acme-web/access", json={"user_id": str(outsider.id)})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_grant_and_list_and_revoke_client_access(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web", pool_name="acme", restrict_access=True)
    user = await create_user(db_session, email="member@example.com", pool_name="acme")

    resp = await client.post("/admin/api/clients/acme-web/access", json={"user_id": str(user.id)})
    assert resp.status_code == 201

    listing = await client.get("/admin/api/clients/acme-web/access")
    assert listing.json() == [{"user_id": str(user.id), "email": "member@example.com"}]

    resp = await client.delete(f"/admin/api/clients/acme-web/access/{user.id}")
    assert resp.status_code == 204

    listing = await client.get("/admin/api/clients/acme-web/access")
    assert listing.json() == []


@pytest.mark.asyncio
async def test_create_list_and_delete_client_role(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web", pool_name="acme")

    resp = await client.post("/admin/api/clients/acme-web/roles", json={"name": "editor"})
    assert resp.status_code == 201
    assert resp.json() == {"name": "editor"}

    # Duplicate name for the same app is rejected.
    resp = await client.post("/admin/api/clients/acme-web/roles", json={"name": "editor"})
    assert resp.status_code == 400

    listing = await client.get("/admin/api/clients/acme-web/roles")
    assert listing.json() == ["editor"]

    resp = await client.delete("/admin/api/clients/acme-web/roles/editor")
    assert resp.status_code == 204
    listing = await client.get("/admin/api/clients/acme-web/roles")
    assert listing.json() == []


@pytest.mark.asyncio
async def test_assign_and_unassign_user_role(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web", pool_name="acme")
    user = await create_user(db_session, email="member@example.com", pool_name="acme")
    await client.post("/admin/api/clients/acme-web/roles", json={"name": "editor"})

    resp = await client.post(f"/admin/api/users/{user.id}/roles", json={"client_id": "acme-web", "role": "editor"})
    assert resp.status_code == 201

    listing = await client.get("/admin/api/clients/acme-web/user-roles")
    row = next(r for r in listing.json() if r["user_id"] == str(user.id))
    assert row["roles"] == ["editor"]

    resp = await client.delete(f"/admin/api/users/{user.id}/roles/acme-web/editor")
    assert resp.status_code == 204
    listing = await client.get("/admin/api/clients/acme-web/user-roles")
    row = next(r for r in listing.json() if r["user_id"] == str(user.id))
    assert row["roles"] == []


@pytest.mark.asyncio
async def test_cannot_assign_a_role_from_a_different_login_group(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web", pool_name="acme")
    outsider = await create_user(db_session, email="outsider@example.com", pool_name="other-pool")
    await client.post("/admin/api/clients/acme-web/roles", json={"name": "editor"})

    resp = await client.post(
        f"/admin/api/users/{outsider.id}/roles", json={"client_id": "acme-web", "role": "editor"}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_deleting_a_role_removes_its_assignments(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web", pool_name="acme")
    user = await create_user(db_session, email="member@example.com", pool_name="acme")
    await client.post("/admin/api/clients/acme-web/roles", json={"name": "editor"})
    await client.post(f"/admin/api/users/{user.id}/roles", json={"client_id": "acme-web", "role": "editor"})

    resp = await client.delete("/admin/api/clients/acme-web/roles/editor")
    assert resp.status_code == 204

    from sqlalchemy import select

    from app.db.models import UserRoleAssignment

    remaining = await db_session.execute(select(UserRoleAssignment))
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_edit_client(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web")

    resp = await client.patch(
        "/admin/api/clients/acme-web",
        json={"client_name": "Acme Web", "redirect_uris": "https://acme.example.com/cb", "scope": "openid email"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_name"] == "Acme Web"
    assert body["redirect_uris"] == ["https://acme.example.com/cb"]
    assert body["allowed_scope"] == "openid email"


@pytest.mark.asyncio
async def test_delete_client_is_a_real_delete(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web")

    resp = await client.delete("/admin/api/clients/acme-web")
    assert resp.status_code == 204

    listing = await client.get("/admin/api/clients")
    assert all(c["client_id"] != "acme-web" for c in listing.json())

    result = await db_session.execute(select(Client).where(Client.client_id == "acme-web"))
    assert result.scalar_one_or_none() is None

    # Deleting again (already gone) is a 404, not a silent no-op.
    resp = await client.delete("/admin/api/clients/acme-web")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_client_cascades_through_dependents(client, db_session):
    """A real DELETE on a client must not 500 with a foreign-key violation
    just because it has roles, access grants, consents, or tokens."""
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="acme-web", restrict_access=True)
    user = await create_user(db_session, email="member@example.com", pool_name="default")

    await client.post("/admin/api/clients/acme-web/access", json={"user_id": str(user.id)})
    await client.post("/admin/api/clients/acme-web/roles", json={"name": "editor"})
    await client.post(f"/admin/api/users/{user.id}/roles", json={"client_id": "acme-web", "role": "editor"})

    from app.db.models import Consent, RefreshToken
    from app.auth.passwords import hash_password

    db_session.add(Consent(user_id=user.id, client_id="acme-web", scopes=["openid"]))
    db_session.add(
        RefreshToken(
            user_id=str(user.id),
            client_id="acme-web",
            resource_id="https://api.example.com",
            token_hash=hash_password("irrelevant-raw-token-value"),
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    await db_session.commit()

    resp = await client.delete("/admin/api/clients/acme-web")
    assert resp.status_code == 204

    result = await db_session.execute(select(Client).where(Client.client_id == "acme-web"))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_create_user_via_admin(client, db_session):
    await _login_admin(client, db_session)

    resp = await client.post(
        "/admin/api/users",
        json={
            "email": "newuser@example.com",
            "password": "s3cret-password!",
            "confirm_password": "s3cret-password!",
            "user_pool": "default",
        },
    )
    assert resp.status_code == 201

    result = await db_session.execute(select(User).where(User.email == "newuser@example.com"))
    saved = result.scalar_one()
    assert saved is not None
    # Defaults to verified -- an admin adding someone is itself vouching for them.
    assert saved.email_verified is True


@pytest.mark.asyncio
async def test_create_user_rejects_mismatched_passwords(client, db_session):
    await _login_admin(client, db_session)

    resp = await client.post(
        "/admin/api/users",
        json={
            "email": "newuser@example.com",
            "password": "s3cret-password!",
            "confirm_password": "something-else!",
            "user_pool": "default",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_user_unverified_sends_verification_email(client, db_session, monkeypatch):
    await _login_admin(client, db_session)

    sent = {}

    async def fake_send(email, token):
        sent["email"] = email

    monkeypatch.setattr("app.admin.api.send_verification_email", fake_send)

    resp = await client.post(
        "/admin/api/users",
        json={
            "email": "unverified@example.com",
            "password": "s3cret-password!",
            "confirm_password": "s3cret-password!",
            "user_pool": "default",
            "email_verified": False,
        },
    )
    assert resp.status_code == 201
    assert sent.get("email") == "unverified@example.com"


@pytest.mark.asyncio
async def test_edit_user_email(client, db_session):
    await _login_admin(client, db_session)
    user = await create_user(db_session, email="old@example.com")

    resp = await client.patch(f"/admin/api/users/{user.id}", json={"email": "new@example.com"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "new@example.com"

    # Can't collide with another user already in the same login group.
    other = await create_user(db_session, email="taken@example.com")
    resp = await client.patch(f"/admin/api/users/{user.id}", json={"email": other.email})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_edit_user_blank_pool_keeps_current_group(client, db_session):
    await _login_admin(client, db_session)
    user = await create_user(db_session, email="alice@example.com", pool_name="acme")

    resp = await client.patch(f"/admin/api/users/{user.id}", json={"email": "alice@example.com", "user_pool": ""})
    assert resp.status_code == 200
    assert resp.json()["pool_name"] == "acme"


@pytest.mark.asyncio
async def test_edit_user_moves_pool_and_revokes_sessions_and_tokens(client, db_session, redis_client):
    await _login_admin(client, db_session)
    user = await create_user(db_session, email="alice@example.com", pool_name="acme")

    from app.auth.sessions import create_session
    from app.oidc.refresh import issue_refresh_token

    session_id = await create_session(redis_client, str(user.id))
    refresh_token = await issue_refresh_token(
        db_session, redis_client, str(user.id), "test-client", "https://api.example.com", scope="profile"
    )

    resp = await client.patch(
        f"/admin/api/users/{user.id}", json={"email": "alice@example.com", "user_pool": "contractors"}
    )
    assert resp.status_code == 200
    assert resp.json()["pool_name"] == "contractors"

    import hashlib

    assert await redis_client.exists(f"session:{session_id}") == 0
    assert await redis_client.exists(f"refresh:{hashlib.sha256(refresh_token.encode()).hexdigest()}") == 0


@pytest.mark.asyncio
async def test_edit_user_cannot_move_into_a_pool_with_email_collision(client, db_session):
    await _login_admin(client, db_session)
    user = await create_user(db_session, email="alice@example.com", pool_name="acme")
    await create_user(db_session, email="alice@example.com", pool_name="contractors")

    resp = await client.patch(
        f"/admin/api/users/{user.id}", json={"email": "alice@example.com", "user_pool": "contractors"}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_user_hard_deletes(client, db_session):
    await _login_admin(client, db_session)
    user = await create_user(db_session, email="gone@example.com")
    user_id = user.id

    resp = await client.delete(f"/admin/api/users/{user.id}")
    assert resp.status_code == 204

    listing = await client.get("/admin/api/users")
    assert all(u["email"] != "gone@example.com" for u in listing.json())

    from app.db.models import User as UserModel
    assert (await db_session.get(UserModel, user_id)) is None


@pytest.mark.asyncio
async def test_change_admin_password(client, db_session):
    admin = await _login_admin(client, db_session, email="admin@example.com", password="old-password!")

    wrong = await client.post(
        "/admin/api/account/password",
        json={
            "current_password": "not-the-password",
            "new_password": "new-password!",
            "confirm_password": "new-password!",
        },
    )
    assert wrong.status_code == 400
    assert "incorrect" in wrong.json()["detail"]

    resp = await client.post(
        "/admin/api/account/password",
        json={
            "current_password": "old-password!",
            "new_password": "new-password!",
            "confirm_password": "new-password!",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is False

    await db_session.refresh(admin)
    assert admin.must_change_password is False


@pytest.mark.asyncio
async def test_signup_disabled_for_admin_only_client(client, db_session):
    await create_client(
        db_session,
        client_id="admin-only-app",
        redirect_uris=("https://app.example.com/cb",),
        pool_name="default",
        allow_signup=False,
    )
    from tests.helpers import make_pkce_pair

    _, challenge = make_pkce_pair()
    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "admin-only-app",
            "redirect_uri": "https://app.example.com/cb",
            "resource": "https://api.example.com",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert resp.status_code == 200
    assert "Sign up" not in resp.text

    from tests.helpers import extract_hidden_value

    flow_id = extract_hidden_value(resp.text, "flow_id")
    signup_resp = await client.get("/signup", params={"flow_id": flow_id})
    assert signup_resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_send_password_reset(client, db_session, monkeypatch):
    from unittest.mock import AsyncMock

    send_mock = AsyncMock()
    monkeypatch.setattr("app.email.send_email", send_mock)

    await _login_admin(client, db_session)
    user = await create_user(db_session, email="alice@example.com")

    resp = await client.post(f"/admin/api/users/{user.id}/send-reset")
    assert resp.status_code == 204

    send_mock.assert_awaited_once()
    assert send_mock.await_args.args[0] == "alice@example.com"
    assert "reset-password?token=" in send_mock.await_args.args[2]


@pytest.mark.asyncio
async def test_setup_status_reflects_whether_an_admin_exists(client, db_session):
    resp = await client.get("/admin/api/setup-status")
    assert resp.status_code == 200
    assert resp.json() == {"needs_setup": True}

    await create_admin(db_session)

    resp = await client.get("/admin/api/setup-status")
    assert resp.json() == {"needs_setup": False}


@pytest.mark.asyncio
async def test_setup_creates_admin_and_logs_in(client, db_session):
    resp = await client.post(
        "/admin/api/setup",
        json={"email": "owner@example.com", "password": "a-strong-password!", "confirm_password": "a-strong-password!"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "owner@example.com"
    assert body["must_change_password"] is False

    # Logged in immediately -- the session cookie from setup works for /me.
    me = await client.get("/admin/api/me")
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"

    result = await db_session.execute(select(AdminUser))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_setup_refuses_once_an_admin_exists(client, db_session):
    await create_admin(db_session, email="first@example.com")

    resp = await client.post(
        "/admin/api/setup",
        json={"email": "second@example.com", "password": "a-strong-password!", "confirm_password": "a-strong-password!"},
    )
    assert resp.status_code == 409

    result = await db_session.execute(select(AdminUser))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_setup_rejects_mismatched_or_short_passwords(client):
    mismatched = await client.post(
        "/admin/api/setup",
        json={"email": "owner@example.com", "password": "a-strong-password!", "confirm_password": "different!"},
    )
    assert mismatched.status_code == 400

    short = await client.post(
        "/admin/api/setup",
        json={"email": "owner@example.com", "password": "short", "confirm_password": "short"},
    )
    assert short.status_code == 400
