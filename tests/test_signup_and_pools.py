import pytest
from sqlalchemy import select

from app.db.models import User
from tests.helpers import create_client, create_resource, create_user, extract_hidden_value, make_pkce_pair

REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"


async def _start_flow(client, db_session, client_id="test-client", pool_name="default"):
    await create_client(db_session, client_id=client_id, redirect_uris=(REDIRECT_URI,), pool_name=pool_name)
    await create_resource(db_session, resource_id=RESOURCE)
    _, challenge = make_pkce_pair()

    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "profile email",
        },
    )
    assert resp.status_code == 200
    assert "Sign up" in resp.text
    return extract_hidden_value(resp.text, "flow_id")


@pytest.mark.asyncio
async def test_signup_creates_user_and_reaches_consent(client, db_session):
    flow_id = await _start_flow(client, db_session)

    page = await client.get("/signup", params={"flow_id": flow_id})
    assert page.status_code == 200
    assert "Create your account" in page.text

    resp = await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "email": "newuser@example.com",
            "password": "s3cret-password!",
            "confirm_password": "s3cret-password!",
        },
    )
    assert resp.status_code == 200
    assert "is requesting access" in resp.text

    result = await db_session.execute(select(User).where(User.email == "newuser@example.com"))
    assert result.scalar_one() is not None


@pytest.mark.asyncio
async def test_signup_password_mismatch_rejected(client, db_session):
    flow_id = await _start_flow(client, db_session)

    resp = await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "email": "newuser@example.com",
            "password": "s3cret-password!",
            "confirm_password": "different-password!",
        },
    )
    assert resp.status_code == 400
    assert "do not match" in resp.text


@pytest.mark.asyncio
async def test_signup_short_password_rejected(client, db_session):
    flow_id = await _start_flow(client, db_session)

    resp = await client.post(
        "/signup",
        data={"flow_id": flow_id, "email": "newuser@example.com", "password": "short", "confirm_password": "short"},
    )
    assert resp.status_code == 400
    assert "at least" in resp.text


@pytest.mark.asyncio
async def test_signup_duplicate_email_in_same_pool_rejected(client, db_session):
    await create_user(db_session, email="alice@example.com", password="s3cret-password!", pool_name="default")
    flow_id = await _start_flow(client, db_session, pool_name="default")

    resp = await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "email": "alice@example.com",
            "password": "another-password!",
            "confirm_password": "another-password!",
        },
    )
    assert resp.status_code == 400
    assert "already exists" in resp.text


@pytest.mark.asyncio
async def test_signup_same_email_allowed_in_different_pool(client, db_session):
    await create_user(db_session, email="alice@example.com", password="s3cret-password!", pool_name="tenant-a")
    flow_id = await _start_flow(client, db_session, client_id="tenant-b-client", pool_name="tenant-b")

    resp = await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "email": "alice@example.com",
            "password": "another-password!",
            "confirm_password": "another-password!",
        },
    )
    assert resp.status_code == 200
    assert "is requesting access" in resp.text


@pytest.mark.asyncio
async def test_login_works_across_clients_sharing_a_pool(client, db_session):
    await create_user(db_session, email="alice@example.com", password="s3cret-password!", pool_name="acme")
    await create_client(db_session, client_id="acme-web", redirect_uris=(REDIRECT_URI,), pool_name="acme")
    await create_client(db_session, client_id="acme-mobile", redirect_uris=(REDIRECT_URI,), pool_name="acme")
    await create_resource(db_session, resource_id=RESOURCE)
    _, challenge = make_pkce_pair()

    for client_id in ("acme-web", "acme-mobile"):
        resp = await client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "resource": RESOURCE,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "profile email",
            },
        )
        flow_id = extract_hidden_value(resp.text, "flow_id")
        login_resp = await client.post(
            "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "s3cret-password!"}
        )
        assert login_resp.status_code == 200
        assert "is requesting access" in login_resp.text


@pytest.mark.asyncio
async def test_login_rejected_across_isolated_pools(client, db_session):
    await create_user(db_session, email="alice@example.com", password="s3cret-password!", pool_name="tenant-a")
    await create_client(db_session, client_id="tenant-b-client", redirect_uris=(REDIRECT_URI,), pool_name="tenant-b")
    await create_resource(db_session, resource_id=RESOURCE)
    _, challenge = make_pkce_pair()

    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "tenant-b-client",
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "profile email",
        },
    )
    flow_id = extract_hidden_value(resp.text, "flow_id")

    login_resp = await client.post(
        "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "s3cret-password!"}
    )
    assert login_resp.status_code == 401
    assert "Invalid email or password" in login_resp.text


@pytest.mark.asyncio
async def test_existing_session_not_reused_across_isolated_pools(client, db_session):
    await create_user(db_session, email="alice@example.com", password="s3cret-password!", pool_name="tenant-a")
    await create_client(db_session, client_id="tenant-a-client", redirect_uris=(REDIRECT_URI,), pool_name="tenant-a")
    await create_client(db_session, client_id="tenant-b-client", redirect_uris=(REDIRECT_URI,), pool_name="tenant-b")
    await create_resource(db_session, resource_id=RESOURCE)
    _, challenge = make_pkce_pair()

    resp_a = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "tenant-a-client",
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "profile email",
        },
    )
    flow_id_a = extract_hidden_value(resp_a.text, "flow_id")
    login_resp = await client.post(
        "/login", data={"flow_id": flow_id_a, "email": "alice@example.com", "password": "s3cret-password!"}
    )
    assert login_resp.status_code == 200  # logged in, session cookie now set for tenant-a's pool

    resp_b = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "tenant-b-client",
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "profile email",
        },
    )
    # Must NOT skip straight to consent using the tenant-a session -- back to login/signup.
    assert resp_b.status_code == 200
    assert "Sign in" in resp_b.text
