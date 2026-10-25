import pytest
from sqlalchemy import select

from app.db.models import Client
from tests.helpers import create_client


@pytest.mark.asyncio
async def test_register_public_client(client):
    resp = await client.post(
        "/register",
        json={
            "redirect_uris": ["https://app.example.com/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_method": "none",
            "application_type": "native",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "client_id" in body
    assert "client_secret" not in body


@pytest.mark.asyncio
async def test_register_confidential_client(client):
    resp = await client.post(
        "/register",
        json={
            "redirect_uris": ["https://app.example.com/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "client_secret" in body


@pytest.mark.asyncio
async def test_register_refuses_client_credentials(client):
    """Anyone can call /register -- a client that could mint tokens on its
    own authority would hand out tokens for any API to anyone."""
    resp = await client.post(
        "/register",
        json={"grant_types": ["client_credentials"], "token_endpoint_auth_method": "client_secret_post"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_register_drops_scopes_outside_the_self_registration_list(client, db_session):
    resp = await client.post(
        "/register",
        json={
            "redirect_uris": ["https://app.example.com/callback"],
            "token_endpoint_auth_method": "none",
            "scope": "openid email admin",
        },
    )
    assert resp.status_code == 201
    registered = (
        await db_session.execute(select(Client).where(Client.client_id == resp.json()["client_id"]))
    ).scalar_one()
    assert registered.allowed_scope == "openid email"


@pytest.mark.asyncio
async def test_old_self_registered_client_cannot_use_client_credentials(client, db_session):
    """A DCR client stored before /register stopped offering the grant."""
    await create_client(
        db_session,
        client_id="old-dcr",
        client_type="confidential",
        grant_types=("client_credentials",),
        client_secret="s3cret",
    )
    row = (await db_session.execute(select(Client).where(Client.client_id == "old-dcr"))).scalar_one()
    row.registration_method = "dcr"
    await db_session.commit()

    resp = await client.post(
        "/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "old-dcr",
            "client_secret": "s3cret",
            "resource": "https://api.example.com",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_register_rejects_unknown_grant_type(client):
    resp = await client.post(
        "/register",
        json={"grant_types": ["not_a_real_grant"], "token_endpoint_auth_method": "none"},
    )
    assert resp.status_code == 400
