"""Embedded sign-in (app/oidc/embed.py): an application's page shows this
service's login/signup in an iframe and gets a one-time code by postMessage."""

import json
import re

import pytest
from sqlalchemy import select

from app.db.models import Client, Consent
from app.oidc.embed import parse_appearance
from tests.helpers import create_admin, create_client, create_resource, create_user, extract_hidden_value, make_pkce_pair

ORIGIN = "https://app.example.com"
RESOURCE = "https://api.example.com"


async def _embeddable_client(db_session, origins=(ORIGIN,), **kwargs):
    await create_client(db_session, client_id="test-client", **kwargs)
    await create_resource(db_session, resource_id=RESOURCE)
    client = (await db_session.execute(select(Client).where(Client.client_id == "test-client"))).scalar_one()
    client.embed_origins = list(origins)
    await db_session.commit()
    return client


def _embed_params(challenge, **overrides):
    params = {
        "response_type": "code",
        "response_mode": "web_message",
        "client_id": "test-client",
        "resource": RESOURCE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "profile email",
        "state": "st-1",
        "origin": ORIGIN,
        "frame_id": "frame-1",
    }
    params.update(overrides)
    return params


def _data_attr(html, name):
    match = re.search(rf'data-{name}="([^"]*)"', html)
    assert match, f"data-{name} missing"
    return match.group(1)


@pytest.mark.asyncio
async def test_embed_page_may_be_framed_only_by_the_registered_origin(client, db_session):
    await _embeddable_client(db_session)
    _, challenge = make_pkce_pair()

    resp = await client.get("/authorize", params=_embed_params(challenge))

    assert resp.status_code == 200
    assert resp.headers["content-security-policy"] == f"frame-ancestors {ORIGIN}"
    assert "x-frame-options" not in resp.headers
    assert 'class="embed"' in resp.text
    assert _data_attr(resp.text, "embed-origin") == ORIGIN


@pytest.mark.asyncio
async def test_normal_pages_still_refuse_all_framing(client, db_session):
    await _embeddable_client(db_session)
    _, challenge = make_pkce_pair()
    params = _embed_params(challenge, response_mode="query", redirect_uri="https://client.example.com/callback")
    del params["origin"], params["frame_id"]

    resp = await client.get("/authorize", params=params)

    assert resp.status_code == 200
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert 'class="embed"' not in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"origin": "https://evil.example.com"},  # not listed for this client
        {"origin": None},
        {"frame_id": None},
        {"frame_id": "bad id with spaces"},
    ],
)
async def test_embedding_refused_for_unlisted_origin_or_bad_frame(client, db_session, overrides):
    await _embeddable_client(db_session)
    _, challenge = make_pkce_pair()
    params = {k: v for k, v in _embed_params(challenge, **overrides).items() if v is not None}

    resp = await client.get("/authorize", params=params)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_client_without_embed_origins_cannot_be_embedded(client, db_session):
    await _embeddable_client(db_session, origins=())
    _, challenge = make_pkce_pair()

    resp = await client.get("/authorize", params=_embed_params(challenge))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_embedded_login_posts_a_code_that_exchanges_for_tokens(client, db_session):
    await _embeddable_client(db_session)
    await create_user(db_session, email="alice@example.com", password="s3cret-password!")
    verifier, challenge = make_pkce_pair()

    page = await client.get("/authorize", params=_embed_params(challenge))
    flow_id = extract_hidden_value(page.text, "flow_id")
    done = await client.post(
        "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "s3cret-password!"}
    )

    # No consent screen and no redirect: a page that hands the code to the
    # embedding origin, framable only by it.
    assert done.status_code == 200
    assert done.headers["content-security-policy"] == f"frame-ancestors {ORIGIN}"
    assert done.headers["cache-control"] == "no-store"
    assert _data_attr(done.text, "result") == "success"
    assert _data_attr(done.text, "embed-origin") == ORIGIN
    assert _data_attr(done.text, "frame-id") == "frame-1"
    assert _data_attr(done.text, "state") == "st-1"
    code = _data_attr(done.text, "code")

    tokens = await client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "client_id": "test-client"},
    )
    assert tokens.status_code == 200
    assert "access_token" in tokens.json()

    consent = (await db_session.execute(select(Consent))).scalar_one()
    assert set(consent.scopes) == {"profile", "email"}


@pytest.mark.asyncio
async def test_embedded_code_needs_the_pkce_verifier(client, db_session):
    await _embeddable_client(db_session)
    await create_user(db_session, email="alice@example.com", password="s3cret-password!")
    _, challenge = make_pkce_pair()

    page = await client.get("/authorize", params=_embed_params(challenge))
    flow_id = extract_hidden_value(page.text, "flow_id")
    done = await client.post(
        "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "s3cret-password!"}
    )
    wrong_verifier, _ = make_pkce_pair()

    tokens = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": _data_attr(done.text, "code"),
            "code_verifier": wrong_verifier,
            "client_id": "test-client",
        },
    )
    assert tokens.status_code == 400


@pytest.mark.asyncio
async def test_failed_login_stays_inside_the_embed(client, db_session):
    await _embeddable_client(db_session)
    await create_user(db_session, email="alice@example.com", password="s3cret-password!")
    _, challenge = make_pkce_pair()

    page = await client.get("/authorize", params=_embed_params(challenge))
    flow_id = extract_hidden_value(page.text, "flow_id")
    resp = await client.post("/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "wrong"})

    assert resp.status_code == 401
    assert resp.headers["content-security-policy"] == f"frame-ancestors {ORIGIN}"
    assert 'class="embed"' in resp.text
    assert "Invalid email or password" in resp.text


@pytest.mark.asyncio
async def test_signup_screen_can_be_opened_directly(client, db_session):
    await _embeddable_client(db_session)
    _, challenge = make_pkce_pair()

    resp = await client.get("/authorize", params=_embed_params(challenge, screen="signup"))

    assert resp.status_code == 200
    assert "Create account" in resp.text
    assert 'class="embed"' in resp.text


@pytest.mark.asyncio
async def test_forgot_password_stays_inside_the_embed(client, db_session):
    await _embeddable_client(db_session)
    await create_user(db_session, email="alice@example.com", password="s3cret-password!")
    _, challenge = make_pkce_pair()

    page = await client.get("/authorize", params=_embed_params(challenge))
    assert 'target="_blank"' not in page.text
    flow_id = extract_hidden_value(page.text, "flow_id")

    forgot = await client.get("/forgot-password", params={"flow_id": flow_id})
    assert forgot.headers["content-security-policy"] == f"frame-ancestors {ORIGIN}"
    assert "x-frame-options" not in forgot.headers
    assert 'class="embed"' in forgot.text
    assert f'href="/login?flow_id={flow_id}"' in forgot.text  # back to sign in, still in the frame

    sent = await client.post("/forgot-password", data={"flow_id": flow_id, "email": "alice@example.com"})
    assert sent.headers["content-security-policy"] == f"frame-ancestors {ORIGIN}"
    assert 'class="embed"' in sent.text


@pytest.mark.asyncio
async def test_forgot_password_outside_an_embed_is_unchanged(client, db_session):
    await _embeddable_client(db_session)
    _, challenge = make_pkce_pair()
    params = _embed_params(challenge, response_mode="query", redirect_uri="https://client.example.com/callback")
    del params["origin"], params["frame_id"]

    page = await client.get("/authorize", params=params)
    forgot = await client.get("/forgot-password", params={"flow_id": extract_hidden_value(page.text, "flow_id")})

    assert forgot.headers["x-frame-options"] == "DENY"
    assert 'class="embed"' not in forgot.text


@pytest.mark.asyncio
async def test_appearance_is_applied(client, db_session):
    await _embeddable_client(db_session)
    _, challenge = make_pkce_pair()
    appearance = json.dumps({"colorPrimary": "#6b4eff", "borderRadius": "14px", "theme": "dark"})

    resp = await client.get("/authorize", params=_embed_params(challenge, appearance=appearance))

    assert "--color-primary: #6b4eff" in resp.text
    assert "--radius-md: 14px" in resp.text
    assert 'data-theme="dark"' in resp.text


def test_appearance_keeps_only_safe_values():
    raw = json.dumps(
        {
            "colorPrimary": "red; } body { display:none",
            "colorText": "url(https://evil.example.com/x)",
            "fontFamily": "'Inter'</style><script>",
            "borderRadius": "12px",
            "colorBackground": "rgb(10, 20, 30)",
            "fontSize": "99px",  # not an option
            "theme": "neon",
        }
    )
    assert parse_appearance(raw) == {"borderRadius": "12px", "colorBackground": "rgb(10, 20, 30)"}
    assert parse_appearance("not json") == {}
    assert parse_appearance(json.dumps(["a"])) == {}


@pytest.mark.asyncio
async def test_admin_sets_and_validates_embed_origins(client, db_session):
    await create_admin(db_session)
    await create_client(db_session, client_id="test-client")
    login = await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})
    assert login.status_code == 200

    ok = await client.patch(
        "/admin/api/clients/test-client",
        json={"client_name": "", "redirect_uris": "", "scope": "", "embed_origins": "https://App.example.com:443/\nhttp://localhost:3000"},
    )
    assert ok.status_code == 200
    assert ok.json()["embed_origins"] == ["https://app.example.com", "http://localhost:3000"]

    for bad in ("http://insecure.example.com", "https://app.example.com/login", "*"):
        resp = await client.patch(
            "/admin/api/clients/test-client",
            json={"client_name": "", "redirect_uris": "", "scope": "", "embed_origins": bad},
        )
        assert resp.status_code == 400, bad


@pytest.mark.asyncio
async def test_embedded_signup_also_ends_with_a_code(client, db_session):
    await _embeddable_client(db_session)
    _, challenge = make_pkce_pair()

    page = await client.get("/authorize", params=_embed_params(challenge, screen="signup"))
    flow_id = extract_hidden_value(page.text, "flow_id")
    done = await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "first_name": "Bea",
            "last_name": "Example",
            "email": "bea@example.com",
            "password": "s3cret-password!",
            "confirm_password": "s3cret-password!",
        },
    )

    assert done.status_code == 200
    assert _data_attr(done.text, "result") == "success"
    assert _data_attr(done.text, "code")


@pytest.mark.asyncio
async def test_wrong_password_keeps_the_typed_email(client, db_session):
    await _embeddable_client(db_session)
    await create_user(db_session, email="alice@example.com", password="s3cret-password!")
    _, challenge = make_pkce_pair()

    page = await client.get("/authorize", params=_embed_params(challenge))
    flow_id = extract_hidden_value(page.text, "flow_id")
    resp = await client.post("/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "wrong"})

    assert 'value="alice@example.com"' in resp.text


@pytest.mark.asyncio
async def test_embedded_signup_waits_for_a_verified_email_inside_the_frame(client, db_session, monkeypatch):
    """With "require a verified email" on, the embedded form shows "check
    your email" in the frame, then hands the page its code once verified."""
    links: list[str] = []

    async def fake_send(to, subject, body):
        links.extend(w for w in body.split() if "/verify-email?token=" in w)

    monkeypatch.setattr("app.email.send_email", fake_send)
    app_client = await _embeddable_client(db_session, allow_signup=True)
    app_client.require_verified_email = True
    await db_session.commit()
    _, challenge = make_pkce_pair()

    form = await client.get("/authorize", params=_embed_params(challenge, screen="signup"))
    flow_id = extract_hidden_value(form.text, "flow_id")
    waiting = await client.post(
        "/signup",
        data={
            "flow_id": flow_id,
            "first_name": "Ava",
            "last_name": "Stone",
            "email": "ava@example.com",
            "password": "ava-password-1",
            "confirm_password": "ava-password-1",
        },
    )
    assert "Check your email" in waiting.text
    assert waiting.headers["content-security-policy"] == f"frame-ancestors {ORIGIN}"
    assert 'class="embed"' in waiting.text

    token = links[0].split("token=")[1]
    assert (await client.get("/verify-email", params={"token": token})).status_code == 200
    done = await client.post("/verify-email/continue", data={"flow_id": flow_id})
    assert done.headers["content-security-policy"] == f"frame-ancestors {ORIGIN}"
    assert _data_attr(done.text, "code")


@pytest.mark.asyncio
async def test_an_apps_own_redirect_site_can_embed_without_extra_setup(client, db_session):
    """Redirect and embedded sign-in both work as soon as the app exists."""
    await _embeddable_client(db_session, origins=(), redirect_uris=(f"{ORIGIN}/auth/callback",))
    _, challenge = make_pkce_pair()

    resp = await client.get("/authorize", params=_embed_params(challenge))
    assert resp.status_code == 200
    assert resp.headers["content-security-policy"] == f"frame-ancestors {ORIGIN}"


@pytest.mark.asyncio
async def test_self_registered_apps_still_cannot_embed(client, db_session):
    app_client = await _embeddable_client(db_session, origins=(), redirect_uris=(f"{ORIGIN}/auth/callback",))
    app_client.registration_method = "dcr"
    await db_session.commit()
    _, challenge = make_pkce_pair()

    assert (await client.get("/authorize", params=_embed_params(challenge))).status_code == 400


def test_local_network_addresses_may_use_plain_http():
    from app.oidc.embed import normalize_origin, origin_of

    assert normalize_origin("http://192.168.100.175:8082/") == "http://192.168.100.175:8082"
    assert normalize_origin("http://10.0.0.5") == "http://10.0.0.5"
    assert normalize_origin("http://localhost:5173") == "http://localhost:5173"
    with pytest.raises(ValueError):
        normalize_origin("http://8.8.8.8")  # a public address needs https
    with pytest.raises(ValueError):
        normalize_origin("http://shop.example.com")

    # Redirect URIs an app opens itself (not a web page) give no origin.
    assert origin_of("com.vendor.app:/callback") is None
    assert origin_of("http://192.168.100.175:8082/") == "http://192.168.100.175:8082"


@pytest.mark.asyncio
async def test_admin_saves_a_local_network_site_and_sees_where_embedding_works(client, db_session):
    await create_admin(db_session, email="admin@example.com", password="admin-password!")
    await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})
    created = await client.post(
        "/admin/api/clients",
        json={"client_id": "vender-app-c", "client_type": "public", "redirect_uris": "http://192.168.100.175:8082/"},
    )
    assert created.json()["embed_allowed_origins"] == ["http://192.168.100.175:8082"]

    resp = await client.patch(
        "/admin/api/clients/vender-app-c",
        json={"redirect_uris": "http://192.168.100.175:8082/", "embed_origins": "http://192.168.100.175:8082/"},
    )
    assert resp.status_code == 200
    assert resp.json()["embed_allowed_origins"] == ["http://192.168.100.175:8082"]
