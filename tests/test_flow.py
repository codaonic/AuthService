from urllib.parse import parse_qs, urlparse

import pytest

from tests.helpers import (
    create_client,
    create_resource,
    create_user,
    extract_hidden_value,
    make_pkce_pair,
)

REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"


async def _run_authorize_to_code(client, db_session, verifier, challenge, password="s3cret-password!"):
    await create_user(db_session, email="alice@example.com", password=password)
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,))
    await create_resource(db_session, resource_id=RESOURCE)

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
            "state": "xyz",
        },
    )
    assert resp.status_code == 200
    flow_id = extract_hidden_value(resp.text, "flow_id")

    login_resp = await client.post(
        "/login",
        data={
            "flow_id": flow_id,
            "email": "alice@example.com",
            "password": password,
        },
    )
    assert login_resp.status_code == 200  # consent screen, no prior consent
    assert "is requesting access" in login_resp.text

    consent_resp = await client.post(
        "/consent", data={"flow_id": flow_id, "approve": "true"}
    )
    assert consent_resp.status_code == 303
    location = consent_resp.headers["location"]
    assert location.startswith(REDIRECT_URI)
    query = parse_qs(urlparse(location).query)
    assert query["state"] == ["xyz"]
    return query["code"][0]


@pytest.mark.asyncio
async def test_full_authorization_code_flow(client, db_session):
    verifier, challenge = make_pkce_pair()
    code = await _run_authorize_to_code(client, db_session, verifier, challenge)

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
    assert token_resp.status_code == 200
    body = token_resp.json()
    assert body["token_type"] == "Bearer"
    assert body["scope"] == "profile email"
    assert "access_token" in body
    assert "refresh_token" in body

    userinfo_resp = await client.get(
        "/userinfo", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert userinfo_resp.status_code == 200
    assert userinfo_resp.json()["email"] == "alice@example.com"

    refresh_resp = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": body["refresh_token"],
            "client_id": "test-client",
        },
    )
    assert refresh_resp.status_code == 200
    new_body = refresh_resp.json()
    assert new_body["access_token"] != body["access_token"]
    assert new_body["scope"] == "profile email"

    reuse_resp = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": body["refresh_token"],
            "client_id": "test-client",
        },
    )
    assert reuse_resp.status_code == 400


@pytest.mark.asyncio
async def test_authorize_rejects_scope_outside_client_allowed(client, db_session):
    await create_user(db_session, email="alice@example.com", password="s3cret-password!")
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,))
    await create_resource(db_session, resource_id=RESOURCE)
    _, challenge = make_pkce_pair()

    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "test-client",
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "profile email admin",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_wrong_pkce_verifier_rejected(client, db_session):
    verifier, challenge = make_pkce_pair()
    code = await _run_authorize_to_code(client, db_session, verifier, challenge)

    resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": "wrong-verifier",
            "client_id": "test-client",
            "redirect_uri": REDIRECT_URI,
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_client_credentials_grant(client, db_session):
    await create_client(
        db_session,
        client_id="service-a",
        client_type="confidential",
        grant_types=("client_credentials",),
        client_secret="service-secret",
    )

    resp = await client.post(
        "/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "service-a",
            "client_secret": "service-secret",
            "resource": RESOURCE,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" not in body
    assert body["scope"] == "profile email"


@pytest.mark.asyncio
async def test_client_credentials_scope_narrowed_to_subset(client, db_session):
    await create_client(
        db_session,
        client_id="service-a",
        client_type="confidential",
        grant_types=("client_credentials",),
        client_secret="service-secret",
    )

    resp = await client.post(
        "/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "service-a",
            "client_secret": "service-secret",
            "resource": RESOURCE,
            "scope": "profile",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["scope"] == "profile"


@pytest.mark.asyncio
async def test_client_credentials_scope_outside_allowed_rejected(client, db_session):
    await create_client(
        db_session,
        client_id="service-a",
        client_type="confidential",
        grant_types=("client_credentials",),
        client_secret="service-secret",
    )

    resp = await client.post(
        "/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "service-a",
            "client_secret": "service-secret",
            "resource": RESOURCE,
            "scope": "admin",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_client_credentials_wrong_secret_rejected(client, db_session):
    await create_client(
        db_session,
        client_id="service-a",
        client_type="confidential",
        grant_types=("client_credentials",),
        client_secret="service-secret",
    )

    resp = await client.post(
        "/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "service-a",
            "client_secret": "not-the-secret",
            "resource": RESOURCE,
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_revoke_then_refresh_fails(client, db_session):
    verifier, challenge = make_pkce_pair()
    code = await _run_authorize_to_code(client, db_session, verifier, challenge)

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
    refresh_token = token_resp.json()["refresh_token"]

    revoke_resp = await client.post(
        "/revoke", data={"token": refresh_token, "client_id": "test-client"}
    )
    assert revoke_resp.status_code == 200

    refresh_resp = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": "test-client",
        },
    )
    assert refresh_resp.status_code == 400
