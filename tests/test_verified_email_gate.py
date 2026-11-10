"""Applications that require a verified email before people get in."""

from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.db.models import Client, User
from tests.helpers import create_admin, create_client, create_resource, create_user, extract_hidden_value

REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"


@pytest.fixture
def sent_links(monkeypatch):
    """Verification links that would have been emailed."""
    links: list[str] = []

    async def fake_send(to, subject, body):
        links.extend(word for word in body.split() if "/verify-email?token=" in word)

    monkeypatch.setattr("app.email.send_email", fake_send)
    return links


async def _app(db_session, require=True, allow_signup=True):
    await create_client(db_session, client_id="shop", redirect_uris=(REDIRECT_URI,), allow_signup=allow_signup)
    await create_resource(db_session, resource_id=RESOURCE)
    client = (await db_session.execute(select(Client).where(Client.client_id == "shop"))).scalar_one()
    client.require_verified_email = require
    await db_session.commit()


async def _start(client, **extra):
    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "shop",
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": "abc",
            "code_challenge_method": "S256",
            **extra,
        },
    )
    assert resp.status_code == 200
    return extract_hidden_value(resp.text, "flow_id")


async def _signup(client, email="nia@example.com"):
    flow_id = await _start(client, screen="signup")
    resp = await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "first_name": "Nia",
            "last_name": "Park",
            "email": email,
            "password": "nia-password-1",
            "confirm_password": "nia-password-1",
        },
    )
    return flow_id, resp


def _token(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


@pytest.mark.asyncio
async def test_signup_waits_for_the_email_then_carries_on(client, db_session, sent_links):
    await _app(db_session)
    flow_id, resp = await _signup(client)
    assert resp.status_code == 200
    assert "Check your email" in resp.text and "nia@example.com" in resp.text
    assert len(sent_links) == 1

    # Not yet: neither the page's check nor a direct continue lets them in.
    assert (await client.get("/verify-email/status", params={"flow_id": flow_id})).json() == {
        "verified": False,
        "expired": False,
    }
    early = await client.post("/verify-email/continue", data={"flow_id": flow_id})
    assert "Check your email" in early.text

    # They open the link (any tab, any device)...
    assert (await client.get("/verify-email", params={"token": _token(sent_links[0])})).status_code == 200
    assert (await client.get("/verify-email/status", params={"flow_id": flow_id})).json()["verified"] is True

    # ...and the waiting page carries on into the app's consent screen.
    done = await client.post("/verify-email/continue", data={"flow_id": flow_id})
    assert done.status_code == 200 and "is requesting access" in done.text


@pytest.mark.asyncio
async def test_unverified_login_is_held_but_verified_login_goes_through(client, db_session, sent_links):
    await _app(db_session)
    await create_user(db_session, email="bo@example.com", password="bo-password-12", client_id="shop")

    flow_id = await _start(client)
    resp = await client.post("/login", data={"flow_id": flow_id, "email": "bo@example.com", "password": "bo-password-12"})
    assert "Check your email" in resp.text
    assert len(sent_links) == 1  # a fresh link is sent for them

    user = (await db_session.execute(select(User).where(User.email == "bo@example.com"))).scalar_one()
    user.email_verified = True
    await db_session.commit()

    flow_id = await _start(client)
    resp = await client.post("/login", data={"flow_id": flow_id, "email": "bo@example.com", "password": "bo-password-12"})
    assert "is requesting access" in resp.text


@pytest.mark.asyncio
async def test_an_existing_session_does_not_skip_the_check(client, db_session, sent_links):
    """Signed in already (here, from the signup itself): coming back through
    /authorize still lands on "check your email"."""
    await _app(db_session)
    await _signup(client)

    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "shop",
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
    )
    assert "Check your email" in resp.text


@pytest.mark.asyncio
async def test_apps_that_do_not_require_it_let_people_straight_in(client, db_session, sent_links):
    await _app(db_session, require=False)
    _, resp = await _signup(client)
    assert "is requesting access" in resp.text
    assert len(sent_links) == 1  # the email still goes out, it just doesn't gate anything


@pytest.mark.asyncio
async def test_resend_is_limited_to_one_a_minute(client, db_session, sent_links):
    await _app(db_session)
    flow_id, _ = await _signup(client)

    resp = await client.post("/verify-email/resend", data={"flow_id": flow_id})
    assert "less than a minute ago" in resp.text
    assert len(sent_links) == 1


@pytest.mark.asyncio
async def test_unknown_or_expired_sign_in(client):
    assert (await client.get("/verify-email/status", params={"flow_id": "nope"})).json()["expired"] is True
    assert (await client.post("/verify-email/continue", data={"flow_id": "nope"})).status_code == 400


# --- Admin console ---


async def _login_admin(client, db_session):
    await create_admin(db_session, email="admin@example.com", password="admin-password!")
    await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})


@pytest.mark.asyncio
async def test_apps_added_from_the_console_require_it_by_default(client, db_session):
    await _login_admin(client, db_session)
    body = {"client_id": "shop", "client_type": "public", "redirect_uris": REDIRECT_URI}
    assert (await client.post("/admin/api/clients", json=body)).json()["require_verified_email"] is True

    optional = {**body, "client_id": "blog", "require_verified_email": False}
    assert (await client.post("/admin/api/clients", json=optional)).json()["require_verified_email"] is False


@pytest.mark.asyncio
async def test_turning_it_on_for_an_existing_app(client, db_session):
    await _login_admin(client, db_session)
    await _app(db_session, require=False)
    await create_user(db_session, email="bo@example.com", client_id="shop")
    await create_user(db_session, email="cy@example.com", client_id="shop")

    assert (await client.get("/admin/api/clients/shop/unverified-users")).json() == {"count": 2}
    resp = await client.post("/admin/api/clients/shop/toggle-require-verified-email")
    assert resp.json()["require_verified_email"] is True


@pytest.mark.asyncio
async def test_admin_can_verify_someone_or_send_a_new_link(client, db_session, redis_client, monkeypatch):
    from app.auth.password_reset import create_email_verification_token
    from app.config import get_settings
    from app.email import held_links, send_verification_email

    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    await _login_admin(client, db_session)
    await _app(db_session)
    user = await create_user(db_session, email="bo@example.com", client_id="shop")

    assert (await client.post(f"/admin/api/users/{user.id}/send-verification")).json() == {"emailed": False}
    token = await create_email_verification_token(redis_client, str(user.id))
    await send_verification_email(redis_client, user.email, token)
    assert len(await held_links(redis_client)) == 2

    body = (await client.post(f"/admin/api/users/{user.id}/mark-verified")).json()
    assert body["email_verified"] is True
    assert await held_links(redis_client) == []  # their waiting links are gone too


# --- Required by the API or MCP server ---


async def _mcp_server(db_session, require=True):
    from app.db.models import Resource

    resource = (await db_session.execute(select(Resource).where(Resource.resource_id == RESOURCE))).scalar_one()
    resource.require_verified_email = require
    await db_session.commit()


async def _self_registered_app(db_session):
    """Like the app an AI client registers for itself when it connects."""
    await _app(db_session, require=False)
    client = (await db_session.execute(select(Client).where(Client.client_id == "shop"))).scalar_one()
    client.registration_method = "dcr"
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_server_that_requires_it_holds_signups_from_self_registered_apps(client, db_session, sent_links):
    await _self_registered_app(db_session)
    await _mcp_server(db_session, require=True)

    flow_id, resp = await _signup(client)
    assert "Check your email" in resp.text

    await client.get("/verify-email", params={"token": _token(sent_links[0])})
    done = await client.post("/verify-email/continue", data={"flow_id": flow_id})
    assert "is requesting access" in done.text


@pytest.mark.asyncio
async def test_a_server_that_does_not_require_it_lets_them_in(client, db_session, sent_links):
    await _self_registered_app(db_session)
    await _mcp_server(db_session, require=False)

    _, resp = await _signup(client)
    assert "is requesting access" in resp.text


@pytest.mark.asyncio
async def test_servers_registered_from_the_console_require_it_by_default(client, db_session):
    await _login_admin(client, db_session)
    created = await client.post("/admin/api/resources", json={"resource_id": "https://mcp.example.com", "name": "MCP"})
    assert created.json()["require_verified_email"] is True

    toggled = await client.post("/admin/api/resources/https://mcp.example.com/toggle-require-verified-email")
    assert toggled.json()["require_verified_email"] is False
