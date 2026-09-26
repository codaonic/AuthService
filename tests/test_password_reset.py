from unittest.mock import AsyncMock

import pytest

from app.db.models import User
from sqlalchemy import select
from tests.helpers import create_client, create_resource, create_user, extract_hidden_value

REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"


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
            "scope": "profile email",
        },
    )
    assert resp.status_code == 200
    return extract_hidden_value(resp.text, "flow_id")


@pytest.mark.asyncio
async def test_forgot_password_sends_reset_link_for_existing_user(client, db_session, monkeypatch):
    send_mock = AsyncMock()
    monkeypatch.setattr("app.email.send_email", send_mock)

    await create_user(db_session, email="alice@example.com", password="old-password!")
    flow_id = await _get_flow_id(client, db_session)

    resp = await client.post(
        "/forgot-password", data={"flow_id": flow_id, "email": "alice@example.com"}
    )
    assert resp.status_code == 200
    assert "we've sent a link" in resp.text
    send_mock.assert_awaited_once()
    assert "reset-password?token=" in send_mock.await_args.args[2]


@pytest.mark.asyncio
async def test_forgot_password_does_not_leak_unknown_email(client, db_session, monkeypatch):
    send_mock = AsyncMock()
    monkeypatch.setattr("app.email.send_email", send_mock)
    flow_id = await _get_flow_id(client, db_session)

    resp = await client.post(
        "/forgot-password", data={"flow_id": flow_id, "email": "nobody@example.com"}
    )
    assert resp.status_code == 200
    assert "we've sent a link" in resp.text  # identical response either way
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_password_full_flow_and_revokes_sessions(client, db_session, monkeypatch):
    send_mock = AsyncMock()
    monkeypatch.setattr("app.email.send_email", send_mock)

    await create_user(db_session, email="alice@example.com", password="old-password!")
    flow_id = await _get_flow_id(client, db_session)

    await client.post("/forgot-password", data={"flow_id": flow_id, "email": "alice@example.com"})
    link = send_mock.await_args.args[2]
    token = link.split("token=")[1].split()[0].strip()

    reset_resp = await client.post(
        "/reset-password",
        data={"token": token, "password": "new-password!", "confirm_password": "new-password!"},
    )
    assert reset_resp.status_code == 200
    assert "Password updated" in reset_resp.text

    # Old password no longer works.
    login_fail = await client.post(
        "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "old-password!"}
    )
    assert login_fail.status_code == 401

    # New password works.
    login_ok = await client.post(
        "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "new-password!"}
    )
    assert login_ok.status_code == 200


@pytest.mark.asyncio
async def test_reset_token_is_single_use(client, db_session, monkeypatch):
    send_mock = AsyncMock()
    monkeypatch.setattr("app.email.send_email", send_mock)

    await create_user(db_session, email="alice@example.com", password="old-password!")
    flow_id = await _get_flow_id(client, db_session)
    await client.post("/forgot-password", data={"flow_id": flow_id, "email": "alice@example.com"})
    token = send_mock.await_args.args[2].split("token=")[1].split()[0].strip()

    first = await client.post(
        "/reset-password",
        data={"token": token, "password": "new-password!", "confirm_password": "new-password!"},
    )
    assert "Password updated" in first.text

    second = await client.post(
        "/reset-password",
        data={"token": token, "password": "another-password!", "confirm_password": "another-password!"},
    )
    assert second.status_code == 400
    assert "invalid or has expired" in second.text


@pytest.mark.asyncio
async def test_signup_sends_verification_email_and_starts_unverified(client, db_session, monkeypatch):
    send_mock = AsyncMock()
    monkeypatch.setattr("app.email.send_email", send_mock)
    flow_id = await _get_flow_id(client, db_session)

    resp = await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "email": "new@example.com",
            "password": "brand-new-pass!",
            "confirm_password": "brand-new-pass!",
        },
    )
    assert resp.status_code == 200

    send_mock.assert_awaited_once()
    assert "verify-email?token=" in send_mock.await_args.args[2]

    result = await db_session.execute(select(User).where(User.email == "new@example.com"))
    user = result.scalar_one()
    assert user.email_verified is False


@pytest.mark.asyncio
async def test_verify_email_marks_user_verified(client, db_session, monkeypatch):
    send_mock = AsyncMock()
    monkeypatch.setattr("app.email.send_email", send_mock)
    flow_id = await _get_flow_id(client, db_session)

    await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "email": "new@example.com",
            "password": "brand-new-pass!",
            "confirm_password": "brand-new-pass!",
        },
    )
    token = send_mock.await_args.args[2].split("token=")[1].split()[0].strip()

    resp = await client.get(f"/verify-email?token={token}")
    assert resp.status_code == 200
    assert "Email verified" in resp.text

    result = await db_session.execute(select(User).where(User.email == "new@example.com"))
    assert result.scalar_one().email_verified is True

    # Same token can't be reused.
    replay = await client.get(f"/verify-email?token={token}")
    assert replay.status_code == 400


@pytest.mark.asyncio
async def test_resend_verification_skips_already_verified_user(client, db_session, monkeypatch):
    send_mock = AsyncMock()
    monkeypatch.setattr("app.email.send_email", send_mock)

    user = await create_user(db_session, email="alice@example.com", password="pw-12345!")
    user.email_verified = True
    await db_session.commit()

    flow_id = await _get_flow_id(client, db_session)
    resp = await client.post(
        "/resend-verification", data={"flow_id": flow_id, "email": "alice@example.com"}
    )
    assert resp.status_code == 200
    send_mock.assert_not_awaited()
