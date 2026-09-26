from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select
from webauthn.helpers import bytes_to_base64url

from app.db.models import WebAuthnCredential
from tests.helpers import create_client, create_resource, create_user, extract_hidden_value

REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"


async def _get_flow_id(client, db_session, client_id="test-client", pool_name="default"):
    await create_client(db_session, client_id=client_id, redirect_uris=(REDIRECT_URI,), pool_name=pool_name)
    await create_resource(db_session, resource_id=RESOURCE)
    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
    )
    assert resp.status_code == 200
    return extract_hidden_value(resp.text, "flow_id")


async def _login_via_password(client, db_session, email="alice@example.com", password="pw-12345!"):
    await create_user(db_session, email=email, password=password)
    flow_id = await _get_flow_id(client, db_session)
    resp = await client.post("/login", data={"flow_id": flow_id, "email": email, "password": password})
    assert resp.status_code == 200  # consent screen -- session cookie is now set
    return flow_id


@pytest.mark.asyncio
async def test_register_passkey_options_returns_challenge(client, db_session):
    await _login_via_password(client, db_session)

    resp = await client.post("/account/webauthn/register/options")
    assert resp.status_code == 200
    body = resp.json()
    assert "challenge" in body
    assert body["user"]["name"] == "alice@example.com"


@pytest.mark.asyncio
async def test_register_passkey_options_requires_session(client, db_session):
    resp = await client.post("/account/webauthn/register/options")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_passkey_full_flow(client, db_session):
    await _login_via_password(client, db_session)

    opts_resp = await client.post("/account/webauthn/register/options")
    assert opts_resp.status_code == 200

    fake_verification = SimpleNamespace(
        credential_id=b"credential-123", credential_public_key=b"public-key-bytes", sign_count=0
    )
    with patch("app.oidc.webauthn.verify_registration_response", return_value=fake_verification):
        verify_resp = await client.post(
            "/account/webauthn/register/verify",
            data={"credential": '{"id": "irrelevant-for-mock"}', "nickname": "MacBook Touch ID"},
        )
    assert verify_resp.status_code == 303
    assert verify_resp.headers["location"] == "/account"

    result = await db_session.execute(select(WebAuthnCredential))
    saved = result.scalar_one()
    assert saved.credential_id == b"credential-123"
    assert saved.nickname == "MacBook Touch ID"

    account_resp = await client.get("/account")
    assert "MacBook Touch ID" in account_resp.text


@pytest.mark.asyncio
async def test_register_passkey_verify_without_options_fails(client, db_session):
    await _login_via_password(client, db_session)

    resp = await client.post(
        "/account/webauthn/register/verify", data={"credential": "{}", "nickname": ""}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_login_options_rejects_account_with_no_passkey(client, db_session):
    await create_user(db_session, email="alice@example.com")
    flow_id = await _get_flow_id(client, db_session)

    resp = await client.post(
        "/webauthn/login/options", data={"flow_id": flow_id, "email": "alice@example.com"}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_login_with_passkey_full_flow(client, db_session):
    user = await create_user(db_session, email="alice@example.com")
    db_session.add(
        WebAuthnCredential(
            user_id=user.id, credential_id=b"credential-123", public_key=b"public-key-bytes", sign_count=3
        )
    )
    await db_session.commit()

    flow_id = await _get_flow_id(client, db_session)

    opts_resp = await client.post(
        "/webauthn/login/options", data={"flow_id": flow_id, "email": "alice@example.com"}
    )
    assert opts_resp.status_code == 200
    allow_ids = [c["id"] for c in opts_resp.json()["allowCredentials"]]
    assert bytes_to_base64url(b"credential-123") in allow_ids

    fake_verification = SimpleNamespace(new_sign_count=42)
    credential_json = f'{{"id": "{bytes_to_base64url(b"credential-123")}"}}'
    with patch("app.oidc.webauthn.verify_authentication_response", return_value=fake_verification):
        verify_resp = await client.post(
            "/webauthn/login/verify", data={"flow_id": flow_id, "credential": credential_json}
        )
    assert verify_resp.status_code == 200
    assert "is requesting access" in verify_resp.text  # consent screen, same as password login

    result = await db_session.execute(select(WebAuthnCredential))
    assert result.scalar_one().sign_count == 42


@pytest.mark.asyncio
async def test_login_with_passkey_rejects_cross_pool_credential(client, db_session):
    user = await create_user(db_session, email="alice@example.com", pool_name="other-pool")
    db_session.add(
        WebAuthnCredential(
            user_id=user.id, credential_id=b"credential-123", public_key=b"public-key-bytes", sign_count=0
        )
    )
    await db_session.commit()

    # Default-pool client/flow -- unrelated to the "other-pool" user above.
    flow_id = await _get_flow_id(client, db_session, pool_name="default")

    fake_verification = SimpleNamespace(new_sign_count=1)
    credential_json = f'{{"id": "{bytes_to_base64url(b"credential-123")}"}}'
    with patch("app.oidc.webauthn.verify_authentication_response", return_value=fake_verification):
        resp = await client.post(
            "/webauthn/login/verify", data={"flow_id": flow_id, "credential": credential_json}
        )
    assert resp.status_code == 400
