import pytest


@pytest.mark.asyncio
async def test_openid_configuration(client):
    resp = await client.get("/.well-known/openid-configuration")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authorization_endpoint"].endswith("/authorize")
    assert body["token_endpoint"].endswith("/token")
    assert body["code_challenge_methods_supported"] == ["S256"]


@pytest.mark.asyncio
async def test_oauth_authorization_server_metadata_matches_oidc_discovery(client):
    """RFC 8414 alias -- several MCP clients probe this path before falling
    back to /.well-known/openid-configuration; both must serve the same doc.
    """
    oidc = await client.get("/.well-known/openid-configuration")
    rfc8414 = await client.get("/.well-known/oauth-authorization-server")
    assert rfc8414.status_code == 200
    assert rfc8414.json() == oidc.json()


@pytest.mark.asyncio
async def test_jwks_has_keys(client):
    resp = await client.get("/jwks.json")
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["kty"] == "RSA"
    assert "kid" in keys[0]
    assert "d" not in keys[0]


@pytest.mark.asyncio
async def test_protected_resource_metadata(client, db_session):
    from tests.helpers import create_resource

    await create_resource(db_session, resource_id="https://api.example.com", name="API")

    resp = await client.get(
        "/.well-known/oauth-protected-resource", params={"resource": "https://api.example.com"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resource"] == "https://api.example.com"

    missing = await client.get(
        "/.well-known/oauth-protected-resource", params={"resource": "https://unknown.example.com"}
    )
    assert missing.status_code == 404
