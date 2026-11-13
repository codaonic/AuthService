"""ID tokens, prompt/max_age/login_hint, introspection, revocation, back-channel
logout to one app, composite roles, signup teams, expiring access, team
managers and the access review."""

import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet
from sqlalchemy import select

from app.db.models import Client, ClientAccessGrant, ClientRole, Team, TeamMember, UserRoleAssignment
from tests.helpers import create_admin, create_client, create_resource, create_user, extract_hidden_value, make_pkce_pair

REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"
PASSWORD = "s3cret-password!"
SECRET = "api-secret-123456"


@pytest.fixture
def sent(monkeypatch):
    """Back-channel logout messages, instead of real HTTP calls."""
    from app.oidc import backchannel

    calls: list[tuple[str, dict]] = []

    async def fake_send(uri, token):
        calls.append((uri, jwt.decode(token, backchannel.get_key_manager().public_key_set()).claims))
        return 200

    monkeypatch.setattr(backchannel, "_send", fake_send)
    return calls


async def _setup(db_session, *, client_id="test-client", pool="default", **opts):
    from app.db.models import Resource

    if (await db_session.execute(select(Resource).where(Resource.resource_id == RESOURCE))).first() is None:
        await create_resource(db_session, resource_id=RESOURCE)
    await create_client(db_session, client_id=client_id, redirect_uris=(REDIRECT_URI,), pool_name=pool)
    app = (await db_session.execute(select(Client).where(Client.client_id == client_id))).scalar_one()
    for key, value in opts.items():
        setattr(app, key, value)
    await db_session.commit()
    return app


async def _authorize(client, client_id="test-client", **params):
    verifier, challenge = make_pkce_pair()
    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "st",
            **params,
        },
    )
    return resp, verifier


async def _sign_in(client, client_id="test-client", email="alice@example.com", **params):
    """Through login and consent to the code; returns (code, verifier)."""
    resp, verifier = await _authorize(client, client_id, **params)
    flow_id = extract_hidden_value(resp.text, "flow_id")
    resp = await client.post("/login", data={"flow_id": flow_id, "email": email, "password": PASSWORD})
    if "is requesting access" in resp.text:
        resp = await client.post("/consent", data={"flow_id": flow_id, "approve": "true"})
    assert resp.status_code == 303, resp.text[:300]
    return parse_qs(urlparse(resp.headers["location"]).query)["code"][0], verifier


async def _tokens(client, code, verifier, client_id="test-client", **extra):
    resp = await client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "client_id": client_id, **extra},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _claims(client, token):
    keys = KeySet.import_key_set((await client.get("/jwks.json")).json())
    return jwt.decode(token, keys).claims


# --- ID token and the authorize parameters ---


@pytest.mark.asyncio
async def test_openid_gives_an_id_token_with_nonce_sid_and_profile(client, db_session):
    await _setup(db_session)
    await create_user(db_session, email="alice@example.com", password=PASSWORD)
    code, verifier = await _sign_in(client, scope="openid email profile", nonce="n-123")
    body = await _tokens(client, code, verifier)

    claims = await _claims(client, body["id_token"])
    assert claims["aud"] == "test-client" and claims["nonce"] == "n-123"
    assert claims["email"] == "alice@example.com" and claims["sid"] and claims["at_hash"] and claims["auth_time"]

    # On refresh: a new ID token, same session, no nonce.
    refreshed = (
        await client.post(
            "/token", data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"], "client_id": "test-client"}
        )
    ).json()
    again = await _claims(client, refreshed["id_token"])
    assert again["sid"] == claims["sid"] and "nonce" not in again


@pytest.mark.asyncio
async def test_no_id_token_without_openid(client, db_session):
    await _setup(db_session)
    await create_user(db_session, email="alice@example.com", password=PASSWORD)
    code, verifier = await _sign_in(client, scope="email")
    assert "id_token" not in await _tokens(client, code, verifier)


@pytest.mark.asyncio
async def test_prompt_none_without_a_session_says_login_required(client, db_session):
    await _setup(db_session)
    resp, _ = await _authorize(client, prompt="none", scope="openid")
    assert resp.status_code == 303
    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert query["error"] == ["login_required"] and query["state"] == ["st"]


@pytest.mark.asyncio
async def test_prompt_none_with_a_session_returns_a_code_silently(client, db_session):
    await _setup(db_session)
    await create_user(db_session, email="alice@example.com", password=PASSWORD)
    await _sign_in(client, scope="openid")
    resp, _ = await _authorize(client, prompt="none", scope="openid")
    assert resp.status_code == 303 and "code=" in resp.headers["location"]


@pytest.mark.asyncio
async def test_prompt_none_needing_consent_says_consent_required(client, db_session):
    await _setup(db_session)
    await create_user(db_session, email="alice@example.com", password=PASSWORD)
    await _sign_in(client, scope="openid")
    resp, _ = await _authorize(client, prompt="none", scope="openid email")
    assert parse_qs(urlparse(resp.headers["location"]).query)["error"] == ["consent_required"]


@pytest.mark.asyncio
async def test_prompt_login_and_max_age_ask_for_the_password_again(client, db_session):
    await _setup(db_session)
    await create_user(db_session, email="alice@example.com", password=PASSWORD)
    await _sign_in(client, scope="openid")
    for params in ({"prompt": "login"}, {"max_age": "0"}):
        resp, _ = await _authorize(client, scope="openid", **params)
        assert resp.status_code == 200 and 'name="password"' in resp.text


@pytest.mark.asyncio
async def test_login_hint_fills_in_the_email(client, db_session):
    await _setup(db_session)
    resp, _ = await _authorize(client, login_hint="bo@example.com")
    assert 'value="bo@example.com"' in resp.text


@pytest.mark.asyncio
async def test_client_secret_basic_works_at_the_token_endpoint(client, db_session):
    await create_resource(db_session, resource_id=RESOURCE)
    await create_client(
        db_session, client_id="svc", client_type="confidential", client_secret=SECRET, grant_types=("client_credentials",)
    )
    basic = base64.b64encode(f"svc:{SECRET}".encode()).decode()
    resp = await client.post(
        "/token", data={"grant_type": "client_credentials", "resource": RESOURCE}, headers={"Authorization": f"Basic {basic}"}
    )
    assert resp.status_code == 200
    bad = base64.b64encode(b"svc:wrong").decode()
    resp = await client.post(
        "/token", data={"grant_type": "client_credentials", "resource": RESOURCE}, headers={"Authorization": f"Basic {bad}"}
    )
    assert resp.status_code == 401


# --- /userinfo, /introspect, /revoke ---


async def _signed_in(client, db_session, scope="openid email"):
    await _setup(db_session)
    await create_client(db_session, client_id="api", client_type="confidential", client_secret=SECRET, grant_types=("client_credentials",))
    await create_user(db_session, email="alice@example.com", password=PASSWORD)
    code, verifier = await _sign_in(client, scope=scope)
    return await _tokens(client, code, verifier)


async def _introspect(client, token, client_id="api", secret=SECRET):
    return (await client.post("/introspect", data={"token": token, "client_id": client_id, "client_secret": secret})).json()


@pytest.mark.asyncio
async def test_userinfo_refuses_an_id_token(client, db_session):
    body = await _signed_in(client, db_session)
    assert (await client.get("/userinfo", headers={"Authorization": f"Bearer {body['id_token']}"})).status_code == 401
    assert (await client.get("/userinfo", headers={"Authorization": f"Bearer {body['access_token']}"})).status_code == 200


@pytest.mark.asyncio
async def test_introspection_reports_live_status(client, db_session):
    body = await _signed_in(client, db_session)
    assert (await _introspect(client, body["access_token"]))["active"] is True
    assert (await _introspect(client, body["id_token"]))["active"] is False

    # Signing out of the app makes the still-unexpired access token inactive.
    await client.get("/logout", params={"client_id": "test-client"})
    assert (await _introspect(client, body["access_token"]))["active"] is False


@pytest.mark.asyncio
async def test_only_confidential_apps_may_introspect(client, db_session):
    body = await _signed_in(client, db_session)
    resp = await client.post("/introspect", data={"token": body["access_token"], "client_id": "test-client"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_revoking_an_access_token(client, db_session):
    body = await _signed_in(client, db_session)
    await client.post("/revoke", data={"token": body["access_token"], "client_id": "test-client"})
    assert (await _introspect(client, body["access_token"]))["active"] is False


@pytest.mark.asyncio
async def test_an_app_cannot_revoke_another_apps_refresh_token(client, db_session):
    body = await _signed_in(client, db_session)
    await client.post("/revoke", data={"token": body["refresh_token"], "client_id": "api", "client_secret": SECRET})
    refreshed = await client.post(
        "/token", data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"], "client_id": "test-client"}
    )
    assert refreshed.status_code == 200


# --- Back-channel logout, to one app only ---


@pytest.mark.asyncio
async def test_logout_tells_only_that_app(client, db_session, sent):
    from app.oidc.backchannel import wait_for_deliveries

    await _setup(db_session, backchannel_logout_uri="https://client.example.com/bc")
    await _setup(db_session, client_id="other", backchannel_logout_uri="https://other.example.com/bc")
    await create_user(db_session, email="alice@example.com", password=PASSWORD)
    code, verifier = await _sign_in(client, scope="openid")
    id_token = (await _tokens(client, code, verifier))["id_token"]
    sid = (await _claims(client, id_token))["sid"]

    # Logging out by ID token hint instead of client_id.
    await client.get("/logout", params={"id_token_hint": id_token})
    await wait_for_deliveries()
    assert [uri for uri, _ in sent] == ["https://client.example.com/bc"]
    claims = sent[0][1]
    assert claims["aud"] == "test-client" and claims["sid"] == sid
    assert "http://schemas.openid.net/event/backchannel-logout" in claims["events"]
    assert "nonce" not in claims


@pytest.mark.asyncio
async def test_back_channel_logout_url_must_be_https(client, db_session):
    from fastapi import HTTPException

    from app.oidc.backchannel import check_logout_uri

    assert check_logout_uri("https://a.example.com/bc") == "https://a.example.com/bc"
    assert check_logout_uri("http://192.168.1.5:8000/bc")
    with pytest.raises(HTTPException):
        check_logout_uri("http://a.example.com/bc")


# --- Roles ---


async def _admin(client, db_session):
    await create_admin(db_session)
    await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})


@pytest.mark.asyncio
async def test_composite_roles_reach_the_token_and_loops_are_refused(client, db_session):
    await _admin(client, db_session)
    await _setup(db_session, roles_enabled=True, roles_claim="permissions")
    for role in ("admin", "editor", "viewer"):
        db_session.add(ClientRole(client_id="test-client", name=role))
    await db_session.commit()
    user = await create_user(db_session, email="alice@example.com", password=PASSWORD)
    db_session.add(UserRoleAssignment(user_id=user.id, client_id="test-client", role="admin"))
    await db_session.commit()

    assert (await client.put("/admin/api/clients/test-client/roles/admin/includes", json={"includes": ["editor"]})).status_code == 200
    assert (await client.put("/admin/api/clients/test-client/roles/editor/includes", json={"includes": ["viewer"]})).status_code == 200
    loop = await client.put("/admin/api/clients/test-client/roles/viewer/includes", json={"includes": ["admin"]})
    assert loop.status_code == 400

    code, verifier = await _sign_in(client, scope="openid")
    body = await _tokens(client, code, verifier)
    assert (await _claims(client, body["access_token"]))["permissions"] == ["admin", "editor", "viewer"]
    assert (await _claims(client, body["id_token"]))["permissions"] == ["admin", "editor", "viewer"]


@pytest.mark.asyncio
async def test_a_standard_claim_name_cannot_carry_roles(client, db_session):
    await _admin(client, db_session)
    await _setup(db_session)
    resp = await client.patch("/admin/api/clients/test-client", json={"roles_claim": "sub"})
    assert resp.status_code == 400


# --- Teams and access ---


@pytest.mark.asyncio
async def test_signups_join_the_apps_signup_team(client, db_session):
    team = Team(name="Customers")
    db_session.add(team)
    await db_session.commit()
    await _setup(db_session, signup_team_id=team.id, allow_signup=True)
    resp, _ = await _authorize(client, screen="signup")
    await client.post(
        "/signup",
        data={
            "flow_id": extract_hidden_value(resp.text, "flow_id"),
            "first_name": "Bo",
            "last_name": "Li",
            "email": "bo@example.com",
            "password": "bo-password-123",
            "confirm_password": "bo-password-123",
        },
    )
    members = (await db_session.execute(select(TeamMember).where(TeamMember.team_id == team.id))).scalars().all()
    assert len(members) == 1


@pytest.mark.asyncio
async def test_access_that_has_ended_no_longer_lets_them_in(client, db_session):
    await _setup(db_session, restrict_access=True)
    user = await create_user(db_session, email="alice@example.com", password=PASSWORD)
    grant = ClientAccessGrant(client_id="test-client", user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db_session.add(grant)
    await db_session.commit()
    await _sign_in(client)  # still in time

    grant.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    resp, _ = await _authorize(client, prompt="login")
    flow_id = extract_hidden_value(resp.text, "flow_id")
    resp = await client.post("/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": PASSWORD})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_restricting_an_app_signs_out_people_not_on_the_list_now(client, db_session, sent):
    from app.oidc.backchannel import wait_for_deliveries

    await _admin(client, db_session)
    await _setup(db_session, backchannel_logout_uri="https://client.example.com/bc")
    await create_user(db_session, email="alice@example.com", password=PASSWORD)
    code, verifier = await _sign_in(client, scope="openid")
    body = await _tokens(client, code, verifier)

    await client.post("/admin/api/clients/test-client/toggle-restrict-access")
    await wait_for_deliveries()
    assert [uri for uri, _ in sent] == ["https://client.example.com/bc"]
    refreshed = await client.post(
        "/token", data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"], "client_id": "test-client"}
    )
    assert refreshed.status_code == 400


@pytest.mark.asyncio
async def test_new_apps_in_a_restricted_group_start_restricted(client, db_session):
    await _admin(client, db_session)
    await client.post("/admin/api/pools", json={"name": "acme"})
    assert (await client.post("/admin/api/pools/acme/toggle-restrict-new-apps")).json()["restrict_new_apps"] is True
    created = await client.post(
        "/admin/api/clients",
        json={"client_id": "shop", "client_type": "public", "redirect_uris": REDIRECT_URI, "user_pool": "acme"},
    )
    assert created.json()["restrict_access"] is True


@pytest.mark.asyncio
async def test_access_review_says_why_each_person_gets_in(client, db_session):
    await _admin(client, db_session)
    await _setup(db_session, restrict_access=True)
    ana = await create_user(db_session, email="ana@example.com")
    bo = await create_user(db_session, email="bo@example.com")
    await create_user(db_session, email="cy@example.com")  # no access
    db_session.add(ClientAccessGrant(client_id="test-client", user_id=ana.id))
    await db_session.commit()
    team = (await client.post("/admin/api/teams", json={"name": "Staff", "apps": ["test-client"], "members": [str(bo.id)]})).json()
    assert team["member_count"] == 1

    review = (await client.get("/admin/api/clients/test-client/access-review")).json()
    why = {p["email"]: [r["label"] for r in p["reasons"]] for p in review["people"]}
    assert why == {"ana@example.com": ["Let in directly"], "bo@example.com": ["Staff"]}


# --- Team managers, on their own account page ---


async def _manager_setup(client, db_session):
    await _setup(db_session, pool="acme")
    await _setup(db_session, client_id="elsewhere", pool="other")
    boss = await create_user(db_session, email="alice@example.com", password=PASSWORD)
    worker = await create_user(db_session, email="bo@example.com")
    outsider = await create_user(db_session, email="cy@example.com", client_id="elsewhere")
    team = Team(name="Support")
    db_session.add(team)
    await db_session.commit()
    db_session.add(TeamMember(team_id=team.id, user_id=boss.id, is_manager=True))
    await db_session.commit()
    await _sign_in(client)  # the manager's browser session
    return team, worker, outsider


@pytest.mark.asyncio
async def test_a_manager_adds_and_removes_people_in_their_group(client, db_session):
    team, worker, _ = await _manager_setup(client, db_session)
    page = await client.get("/account")
    assert "Team: Support" in page.text

    resp = await client.post(f"/account/teams/{team.id}/members", data={"email": "BO@example.com"})
    assert resp.status_code == 303 and "member_added" in resp.headers["location"]
    resp = await client.post(f"/account/teams/{team.id}/members/{worker.id}/remove")
    assert "member_removed" in resp.headers["location"]


@pytest.mark.asyncio
async def test_a_manager_cannot_reach_outside_their_group_or_remove_managers(client, db_session):
    team, _, _ = await _manager_setup(client, db_session)
    resp = await client.post(f"/account/teams/{team.id}/members", data={"email": "cy@example.com"})
    assert "no_such_person" in resp.headers["location"]
    boss = (await db_session.execute(select(TeamMember).where(TeamMember.is_manager.is_(True)))).scalar_one()
    resp = await client.post(f"/account/teams/{team.id}/members/{boss.user_id}/remove")
    assert "manager_protected" in resp.headers["location"]


@pytest.mark.asyncio
async def test_someone_who_is_not_a_manager_is_refused(client, db_session):
    team, _, _ = await _manager_setup(client, db_session)
    member = (await db_session.execute(select(TeamMember))).scalar_one()
    member.is_manager = False
    await db_session.commit()
    resp = await client.post(f"/account/teams/{team.id}/members", data={"email": "bo@example.com"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_account_page_signs_out_of_one_app_only(client, db_session):
    await _setup(db_session)
    await _setup(db_session, client_id="other")
    await create_user(db_session, email="alice@example.com", password=PASSWORD)
    one = await _tokens(client, *(await _sign_in(client)))
    two = await _tokens(client, *(await _sign_in(client, client_id="other")), client_id="other")
    page = await client.get("/account")
    assert "Apps you&#39;re signed in to" in page.text or "Apps you're signed in to" in page.text

    await client.post("/account/apps/test-client/sign-out")
    refresh = lambda body, cid: client.post(  # noqa: E731
        "/token", data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"], "client_id": cid}
    )
    assert (await refresh(one, "test-client")).status_code == 400
    assert (await refresh(two, "other")).status_code == 200


@pytest.mark.asyncio
async def test_account_messages_are_fixed_text_only(client, db_session):
    await _setup(db_session)
    await create_user(db_session, email="alice@example.com", password=PASSWORD)
    await _sign_in(client)
    page = await client.get("/account", params={"msg": "Your account is locked, call 555-0100", "success": "x"})
    assert "555-0100" not in page.text
