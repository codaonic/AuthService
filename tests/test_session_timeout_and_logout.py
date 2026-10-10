import hashlib
import time
from urllib.parse import parse_qs, urlparse

import pytest

from app.auth.passwords import hash_password
from app.db.models import Client, User
from app.db.pools import get_or_create_pool
from tests.helpers import create_resource, extract_hidden_value, make_pkce_pair

REDIRECT_URI = "https://client.example.com/callback"
LOGGED_OUT_URI = "https://client.example.com/signed-out"
RESOURCE = "https://api.example.com"
EMAIL = "alice@example.com"
PASSWORD = "s3cret-password!"


async def _make_app(db_session, client_id, pool=None, **overrides):
    app = Client(
        user_pool_id=pool.id if pool else None,
        client_id=client_id,
        client_type="public",
        redirect_uris=[REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        allowed_scope="profile email",
        post_logout_redirect_uris=[LOGGED_OUT_URI],
        **overrides,
    )
    db_session.add(app)
    await db_session.commit()
    return app


async def _make_user(db_session, client_id):
    user = User(client_id=client_id, email=EMAIL, password_hash=hash_password(PASSWORD))
    db_session.add(user)
    await db_session.commit()
    return user


async def _authorize(client, client_id, challenge):
    return await client.get(
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


def _asks_for_password(resp) -> bool:
    return 'name="password"' in resp.text


async def _login_and_get_tokens(client, client_id):
    verifier, challenge = make_pkce_pair()
    resp = await _authorize(client, client_id, challenge)
    flow_id = extract_hidden_value(resp.text, "flow_id")
    if _asks_for_password(resp):
        resp = await client.post("/login", data={"flow_id": flow_id, "email": EMAIL, "password": PASSWORD})
    if resp.status_code != 303:  # no earlier consent for this app yet
        resp = await client.post("/consent", data={"flow_id": flow_id, "approve": "true"})
    code = parse_qs(urlparse(resp.headers["location"]).query)["code"][0]
    token_resp = await client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "client_id": client_id},
    )
    assert token_resp.status_code == 200
    return token_resp.json()


async def _grouped_apps(db_session):
    pool = await get_or_create_pool(db_session, "acme")
    await _make_app(db_session, "app-a", pool)
    await _make_app(db_session, "app-b", pool)
    await _make_user(db_session, "app-a")
    await create_resource(db_session, resource_id=RESOURCE)


@pytest.mark.asyncio
async def test_logout_of_one_app_leaves_the_rest_of_its_group_signed_in(client, db_session):
    await _grouped_apps(db_session)
    _, challenge = make_pkce_pair()
    await _login_and_get_tokens(client, "app-a")
    b_tokens = await _login_and_get_tokens(client, "app-b")  # single sign-on, no password

    time.sleep(1.1)
    resp = await client.get("/logout", params={"client_id": "app-a"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "signed_out", "client_id": "app-a"}

    assert _asks_for_password(await _authorize(client, "app-a", challenge))
    assert not _asks_for_password(await _authorize(client, "app-b", challenge))

    refreshed = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": b_tokens["refresh_token"], "client_id": "app-b"},
    )
    assert refreshed.status_code == 200


@pytest.mark.asyncio
async def test_signing_in_to_a_sibling_app_does_not_undo_a_logout(client, db_session, redis_client):
    await _grouped_apps(db_session)
    _, challenge = make_pkce_pair()
    await _login_and_get_tokens(client, "app-a")
    time.sleep(1.1)
    await client.get("/logout", params={"client_id": "app-a"})

    # A fresh password sign-in through app-b...
    await client.get("/logout", params={"client_id": "app-b"})
    time.sleep(1.1)
    await _login_and_get_tokens(client, "app-b")

    # ...still leaves app-a signed out until the user signs in to it directly.
    assert _asks_for_password(await _authorize(client, "app-a", challenge))
    time.sleep(1.1)
    await _login_and_get_tokens(client, "app-a")
    assert not _asks_for_password(await _authorize(client, "app-a", challenge))


@pytest.mark.asyncio
async def test_logout_revokes_that_apps_refresh_tokens(client, db_session):
    await _grouped_apps(db_session)
    tokens = await _login_and_get_tokens(client, "app-a")
    await client.get("/logout", params={"client_id": "app-a"})

    refreshed = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": "app-a"},
    )
    assert refreshed.status_code == 400


@pytest.mark.asyncio
async def test_logout_redirects_only_to_a_registered_uri(client, db_session):
    await _grouped_apps(db_session)

    ok = await client.get(
        "/logout", params={"client_id": "app-a", "post_logout_redirect_uri": LOGGED_OUT_URI, "state": "s1"}
    )
    assert ok.status_code == 303
    assert ok.headers["location"] == f"{LOGGED_OUT_URI}?state=s1"

    bad = await client.get(
        "/logout", params={"client_id": "app-a", "post_logout_redirect_uri": "https://evil.example.com/"}
    )
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_backchannel_logout_with_a_refresh_token(client, db_session):
    await _grouped_apps(db_session)
    _, challenge = make_pkce_pair()
    tokens = await _login_and_get_tokens(client, "app-a")
    time.sleep(1.1)

    # The application's backend calling directly -- identified by the token, not a cookie.
    resp = await client.post("/logout", data={"client_id": "app-a", "refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    assert resp.json()["status"] == "signed_out"

    assert _asks_for_password(await _authorize(client, "app-a", challenge))
    assert not _asks_for_password(await _authorize(client, "app-b", challenge))

    again = await client.post("/logout", data={"client_id": "app-a", "refresh_token": tokens["refresh_token"]})
    assert again.status_code == 400


@pytest.mark.asyncio
async def test_sign_in_older_than_the_apps_timeout_asks_for_password_again(client, db_session, redis_client):
    await _make_app(db_session, "short-app", session_ttl_seconds=600)
    await _make_user(db_session, "short-app")
    await create_resource(db_session, resource_id=RESOURCE)
    _, challenge = make_pkce_pair()

    await _login_and_get_tokens(client, "short-app")
    assert not _asks_for_password(await _authorize(client, "short-app", challenge))

    session_id = client.cookies["auth_session"]
    await redis_client.hset(f"session_apps:{session_id}", "short-app", str(round(time.time()) - 601))
    assert _asks_for_password(await _authorize(client, "short-app", challenge))


@pytest.mark.asyncio
async def test_app_without_a_limit_follows_the_standard_rules(client, db_session, redis_client):
    # The default for API/MCP-style and self-registered clients.
    app = await _make_app(db_session, "mcp-client")
    assert app.session_ttl_seconds == 0
    await _make_user(db_session, "mcp-client")
    await create_resource(db_session, resource_id=RESOURCE)
    _, challenge = make_pkce_pair()
    tokens = await _login_and_get_tokens(client, "mcp-client")

    # A sign-in from long ago is still honored while the session itself lives...
    session_id = client.cookies["auth_session"]
    long_ago = str(round(time.time()) - 20 * 86400)
    await redis_client.hset(f"session_apps:{session_id}", "mcp-client", long_ago)
    assert not _asks_for_password(await _authorize(client, "mcp-client", challenge))

    # ...and refresh tokens keep rotating with the full deployment-wide lifetime.
    refreshed = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": "mcp-client"},
    )
    assert refreshed.status_code == 200
    new_hash = hashlib.sha256(refreshed.json()["refresh_token"].encode()).hexdigest()
    assert await redis_client.ttl(f"refresh:{new_hash}") > 29 * 86400


@pytest.mark.asyncio
async def test_refresh_token_stops_working_after_the_apps_timeout(client, db_session):
    app = await _make_app(db_session, "short-app", session_ttl_seconds=600)
    await _make_user(db_session, "short-app")
    await create_resource(db_session, resource_id=RESOURCE)
    tokens = await _login_and_get_tokens(client, "short-app")

    first = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": "short-app"},
    )
    assert first.status_code == 200

    # The admin shortens the timeout to less than the time already elapsed.
    app.session_ttl_seconds = -5
    await db_session.commit()
    second = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first.json()["refresh_token"],
            "client_id": "short-app",
        },
    )
    assert second.status_code == 400
