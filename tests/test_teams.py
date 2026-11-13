"""Teams: access and roles given to everyone in a team, and its sub-teams."""

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet
from sqlalchemy import select

from app.db.models import Client, ClientRole
from app.oidc.refresh import issue_refresh_token
from tests.helpers import create_admin, create_client, create_resource, create_user, extract_hidden_value

REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"
PASSWORD = "bo-password-123"


async def _admin(client, db_session):
    await create_admin(db_session)
    await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})


async def _team(client, name, parent_id=None):
    resp = await client.post("/admin/api/teams", json={"name": name, "parent_id": parent_id})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _app(db_session, client_id="shop", pool="acme", restrict=True, roles=()):
    await create_client(db_session, client_id=client_id, pool_name=pool, restrict_access=restrict)
    app = (await db_session.execute(select(Client).where(Client.client_id == client_id))).scalar_one()
    app.roles_enabled = bool(roles)
    for role in roles:
        db_session.add(ClientRole(client_id=client_id, name=role))
    await db_session.commit()


async def _login(client, client_id="shop", email="bo@example.com"):
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
    flow_id = extract_hidden_value(resp.text, "flow_id")
    return await client.post("/login", data={"flow_id": flow_id, "email": email, "password": PASSWORD})


async def _token_claims(client, db_session, redis_client, user, client_id="shop"):
    token = await issue_refresh_token(db_session, redis_client, str(user.id), client_id, RESOURCE)
    resp = await client.post("/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": token})
    if resp.status_code != 200:
        return None
    keys = KeySet.import_key_set((await client.get("/jwks.json")).json())
    return jwt.decode(resp.json()["access_token"], keys).claims


@pytest.mark.asyncio
async def test_a_team_lets_its_members_into_a_restricted_app(client, db_session):
    await _admin(client, db_session)
    await create_resource(db_session, resource_id=RESOURCE)
    await _app(db_session)
    user = await create_user(db_session, email="bo@example.com", password=PASSWORD, client_id="shop")
    team = await _team(client, "Staff")

    assert (await _login(client)).status_code == 403  # not on the list yet

    await client.post(f"/admin/api/teams/{team}/apps", json={"client_id": "shop"})
    await client.post(f"/admin/api/teams/{team}/members", json={"user_id": str(user.id)})
    assert (await _login(client)).status_code == 200


@pytest.mark.asyncio
async def test_sub_teams_inherit_roles_and_access(client, db_session, redis_client):
    await _admin(client, db_session)
    await create_resource(db_session, resource_id=RESOURCE)
    await _app(db_session, roles=("viewer", "night-lead"))
    user = await create_user(db_session, email="bo@example.com", client_id="shop")

    support = await _team(client, "Support")
    night = await _team(client, "Night shift", parent_id=support)
    await client.post(f"/admin/api/teams/{support}/apps", json={"client_id": "shop"})
    await client.post(f"/admin/api/teams/{support}/roles", json={"client_id": "shop", "role": "viewer"})
    await client.post(f"/admin/api/teams/{night}/roles", json={"client_id": "shop", "role": "night-lead"})
    await client.post(f"/admin/api/teams/{night}/members", json={"user_id": str(user.id)})

    claims = await _token_claims(client, db_session, redis_client, user)
    assert claims["roles"] == ["night-lead", "viewer"]


@pytest.mark.asyncio
async def test_removing_someone_from_a_team_stops_their_refreshes(client, db_session, redis_client):
    await _admin(client, db_session)
    await create_resource(db_session, resource_id=RESOURCE)
    await _app(db_session)
    user = await create_user(db_session, email="bo@example.com", client_id="shop")
    team = await _team(client, "Staff")
    await client.post(f"/admin/api/teams/{team}/apps", json={"client_id": "shop"})
    await client.post(f"/admin/api/teams/{team}/members", json={"user_id": str(user.id)})
    assert await _token_claims(client, db_session, redis_client, user) is not None

    await client.delete(f"/admin/api/teams/{team}/members/{user.id}")
    assert await _token_claims(client, db_session, redis_client, user) is None


@pytest.mark.asyncio
async def test_a_team_cannot_reach_across_login_groups(client, db_session):
    """Being in a team that has access to an app in another login group
    doesn't let you in: the login group boundary always comes first."""
    await _admin(client, db_session)
    await create_resource(db_session, resource_id=RESOURCE)
    await _app(db_session, client_id="shop", pool="acme")
    await _app(db_session, client_id="bank", pool="other")
    user = await create_user(db_session, email="bo@example.com", password=PASSWORD, client_id="shop")
    team = await _team(client, "Everyone")
    await client.post(f"/admin/api/teams/{team}/apps", json={"client_id": "bank"})
    await client.post(f"/admin/api/teams/{team}/members", json={"user_id": str(user.id)})

    assert (await _login(client, client_id="bank")).status_code == 401


@pytest.mark.asyncio
async def test_team_loops_and_unknown_roles_are_refused(client, db_session):
    await _admin(client, db_session)
    await _app(db_session, roles=("viewer",))
    parent = await _team(client, "Parent")
    child = await _team(client, "Child", parent_id=parent)

    loop = await client.patch(f"/admin/api/teams/{parent}", json={"name": "Parent", "parent_id": child})
    assert loop.status_code == 400
    assert (await client.post("/admin/api/teams", json={"name": "parent"})).status_code == 400  # name taken, any case
    bad_role = await client.post(f"/admin/api/teams/{parent}/roles", json={"client_id": "shop", "role": "owner"})
    assert bad_role.status_code == 400
    assert (await client.delete(f"/admin/api/teams/{parent}")).status_code == 409  # has a sub-team
    assert (await client.delete(f"/admin/api/teams/{child}")).status_code == 204


@pytest.mark.asyncio
async def test_deleting_a_role_or_user_cleans_up_team_rows(client, db_session):
    await _admin(client, db_session)
    await _app(db_session, roles=("viewer",))
    user = await create_user(db_session, email="bo@example.com", client_id="shop")
    team = await _team(client, "Staff")
    await client.post(f"/admin/api/teams/{team}/roles", json={"client_id": "shop", "role": "viewer"})
    await client.post(f"/admin/api/teams/{team}/members", json={"user_id": str(user.id)})

    assert (await client.delete("/admin/api/clients/shop/roles/viewer")).status_code == 204
    assert (await client.delete(f"/admin/api/users/{user.id}")).status_code in (200, 204)
    listed = (await client.get("/admin/api/teams")).json()[0]
    assert listed["roles"] == [] and listed["member_count"] == 0


@pytest.mark.asyncio
async def test_a_team_can_be_set_up_in_one_step(client, db_session):
    await _admin(client, db_session)
    await _app(db_session, roles=("owner",))
    user = await create_user(db_session, email="bo@example.com", client_id="shop")
    body = {
        "name": "Owners",
        "apps": ["shop"],
        "roles": [{"client_id": "shop", "role": "owner"}],
        "members": [str(user.id)],
    }
    team = (await client.post("/admin/api/teams", json=body)).json()
    assert team["apps"][0]["client_id"] == "shop" and team["roles"] == [{"client_id": "shop", "role": "owner"}]
    assert team["member_count"] == 1

    bad = await client.post("/admin/api/teams", json={"name": "Bad", "roles": [{"client_id": "shop", "role": "nope"}]})
    assert bad.status_code == 400
    assert [t["name"] for t in (await client.get("/admin/api/teams")).json()] == ["Owners"]  # nothing half-made


@pytest.mark.asyncio
async def test_set_someones_teams_from_their_panel(client, db_session):
    await _admin(client, db_session)
    await _app(db_session)
    user = await create_user(db_session, email="bo@example.com", client_id="shop")
    a, b = await _team(client, "A"), await _team(client, "B")
    await client.post(f"/admin/api/teams/{a}/members", json={"user_id": str(user.id)})

    resp = await client.put(f"/admin/api/users/{user.id}/teams", json={"team_ids": [b]})
    assert [t["name"] for t in resp.json()] == ["B"]
