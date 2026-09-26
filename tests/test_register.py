import pytest


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
            "grant_types": ["client_credentials"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "client_secret" in body


@pytest.mark.asyncio
async def test_register_rejects_unknown_grant_type(client):
    resp = await client.post(
        "/register",
        json={"grant_types": ["not_a_real_grant"], "token_endpoint_auth_method": "none"},
    )
    assert resp.status_code == 400
