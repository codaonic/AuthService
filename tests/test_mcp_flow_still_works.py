"""An AI assistant connecting to an MCP server, start to finish -- guards that
ID tokens, prompt handling, at+jwt access tokens and live introspection
don't change anything an MCP client or server relies on."""

from urllib.parse import parse_qs, urlparse

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from tests.helpers import create_admin, create_client, create_resource, create_user, extract_hidden_value, make_pkce_pair

MCP = "https://mcp.example.com/mcp"
CALLBACK = "http://localhost:33418/callback"
PASSWORD = "bo-password-123"


async def _connect(client, db_session, scope=""):
    """What Claude/Cursor do: find the server's auth, register, sign the user in."""
    await create_resource(db_session, resource_id=MCP, name="MCP")
    prm = (await client.get("/.well-known/oauth-protected-resource", params={"resource": MCP})).json()
    meta = (await client.get("/.well-known/oauth-authorization-server")).json()
    assert prm["authorization_servers"] == [meta["issuer"]]

    reg = (
        await client.post(
            "/register",
            json={"client_name": "Claude", "redirect_uris": [CALLBACK], "token_endpoint_auth_method": "none"},
        )
    ).json()
    client_id = reg["client_id"]
    await create_user(db_session, email="bo@example.com", password=PASSWORD, client_id=client_id)

    verifier, challenge = make_pkce_pair()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CALLBACK,
        "resource": MCP,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "s",
    }
    if scope:
        params["scope"] = scope
    page = await client.get("/authorize", params=params)
    flow_id = extract_hidden_value(page.text, "flow_id")
    resp = await client.post("/login", data={"flow_id": flow_id, "email": "bo@example.com", "password": PASSWORD})
    if "is requesting access" in resp.text:
        resp = await client.post("/consent", data={"flow_id": flow_id, "approve": "true"})
    code = parse_qs(urlparse(resp.headers["location"]).query)["code"][0]
    tokens = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": client_id,
            "redirect_uri": CALLBACK,
            "resource": MCP,
        },
    )
    assert tokens.status_code == 200, tokens.text
    return client_id, tokens.json()


async def _as_mcp_server_checks_it(client, token):
    """Exactly what the authservice-client validator does."""
    keys = KeySet.import_key_set((await client.get("/jwks.json")).json())
    meta = (await client.get("/.well-known/oauth-authorization-server")).json()
    claims = jwt.decode(token, keys).claims
    JWTClaimsRegistry(iss={"essential": True, "value": meta["issuer"]}, aud={"essential": True, "value": MCP}, exp={"essential": True}).validate(claims)
    return claims


@pytest.mark.asyncio
async def test_an_ai_client_connects_and_its_token_works_at_the_mcp_server(client, db_session):
    client_id, tokens = await _connect(client, db_session)
    assert "id_token" not in tokens  # MCP clients don't ask for openid: nothing new for them
    claims = await _as_mcp_server_checks_it(client, tokens["access_token"])
    assert claims["client_id"] == client_id

    refreshed = await client.post(
        "/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id}
    )
    assert refreshed.status_code == 200
    await _as_mcp_server_checks_it(client, refreshed.json()["access_token"])


@pytest.mark.asyncio
async def test_an_id_token_is_never_accepted_by_the_mcp_server(client, db_session):
    """A client that does ask for openid gets an ID token -- for itself. Its
    audience is the client, so an MCP server's audience check rejects it."""
    _, tokens = await _connect(client, db_session, scope="openid")
    assert "id_token" in tokens
    with pytest.raises(Exception):
        await _as_mcp_server_checks_it(client, tokens["id_token"])


@pytest.mark.asyncio
async def test_an_mcp_server_can_ask_whether_a_token_is_still_good(client, db_session):
    await create_client(db_session, client_id="mcp-server", client_type="confidential", client_secret="srv-secret-1234", grant_types=("client_credentials",))
    _, tokens = await _connect(client, db_session)
    live = await client.post(
        "/introspect", data={"token": tokens["access_token"], "client_id": "mcp-server", "client_secret": "srv-secret-1234"}
    )
    assert live.json()["active"] is True and live.json()["aud"] == MCP


@pytest.mark.asyncio
async def test_turning_off_the_mcp_server_stops_its_tokens(client, db_session):
    await create_admin(db_session)
    await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})
    await create_client(db_session, client_id="mcp-server", client_type="confidential", client_secret="srv-secret-1234", grant_types=("client_credentials",))
    client_id, tokens = await _connect(client, db_session)
    await client.post(f"/admin/api/resources/{MCP}/toggle-enabled")
    live = await client.post(
        "/introspect", data={"token": tokens["access_token"], "client_id": "mcp-server", "client_secret": "srv-secret-1234"}
    )
    assert live.json()["active"] is False
    refreshed = await client.post(
        "/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id}
    )
    assert refreshed.status_code == 400
