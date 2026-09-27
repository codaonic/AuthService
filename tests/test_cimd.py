from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from app.db.models import Client
from tests.helpers import create_resource, create_user, extract_hidden_value, make_pkce_pair

CLIENT_URL = "https://client.example.com/oauth-client.json"
REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._json


def _fake_httpx_client(doc, call_counter):
    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            call_counter["n"] += 1
            assert url == CLIENT_URL
            return _FakeResponse(doc)

    return _FakeAsyncClient


def _valid_doc(**overrides):
    doc = {
        "client_id": CLIENT_URL,
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "scope": "profile email",
    }
    doc.update(overrides)
    return doc


@pytest.mark.asyncio
async def test_cimd_client_resolves_and_registers_on_first_use(client, db_session, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr("app.oidc.cimd.httpx.AsyncClient", _fake_httpx_client(_valid_doc(), calls))
    await create_resource(db_session, resource_id=RESOURCE)

    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": CLIENT_URL,
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
    )
    assert resp.status_code == 200, resp.text
    assert calls["n"] == 1

    result = await db_session.execute(select(Client).where(Client.client_id == CLIENT_URL))
    saved = result.scalar_one()
    assert saved.registration_method == "cimd"
    assert saved.client_type == "public"
    assert saved.redirect_uris == [REDIRECT_URI]


@pytest.mark.asyncio
async def test_cimd_rejects_document_whose_client_id_does_not_match_url(client, db_session, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.oidc.cimd.httpx.AsyncClient",
        _fake_httpx_client(_valid_doc(client_id="https://someone-else.example.com/doc.json"), calls),
    )
    await create_resource(db_session, resource_id=RESOURCE)

    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": CLIENT_URL,
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cimd_client_is_cached_and_not_refetched_within_ttl(client, db_session, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr("app.oidc.cimd.httpx.AsyncClient", _fake_httpx_client(_valid_doc(), calls))
    await create_resource(db_session, resource_id=RESOURCE)

    params = {
        "response_type": "code",
        "client_id": CLIENT_URL,
        "redirect_uri": REDIRECT_URI,
        "resource": RESOURCE,
        "code_challenge": "abc",
        "code_challenge_method": "S256",
    }
    r1 = await client.get("/authorize", params=params)
    r2 = await client.get("/authorize", params=params)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert calls["n"] == 1  # second call served from cache, no refetch


@pytest.mark.asyncio
async def test_cimd_full_flow_issues_a_token(client, db_session, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr("app.oidc.cimd.httpx.AsyncClient", _fake_httpx_client(_valid_doc(), calls))
    await create_resource(db_session, resource_id=RESOURCE)
    await create_user(db_session, email="alice@example.com", password="pw-12345!")

    verifier, challenge = make_pkce_pair()
    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": CLIENT_URL,
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
        },
    )
    flow_id = extract_hidden_value(resp.text, "flow_id")

    login_resp = await client.post(
        "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "pw-12345!"}
    )
    assert login_resp.status_code == 200

    consent_resp = await client.post("/consent", data={"flow_id": flow_id, "approve": "true"})
    assert consent_resp.status_code == 303
    code = parse_qs(urlparse(consent_resp.headers["location"]).query)["code"][0]

    token_resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_URL,
        },
    )
    assert token_resp.status_code == 200, token_resp.text
    assert "access_token" in token_resp.json()


@pytest.mark.asyncio
async def test_cimd_client_rejects_a_client_secret(client, db_session, monkeypatch):
    """CIMD clients are always public -- sending a secret should be rejected,
    not silently accepted."""
    calls = {"n": 0}
    monkeypatch.setattr("app.oidc.cimd.httpx.AsyncClient", _fake_httpx_client(_valid_doc(), calls))
    await create_resource(db_session, resource_id=RESOURCE)

    resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": "bogus",
            "code_verifier": "abc",
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_URL,
            "client_secret": "should-not-be-accepted",
        },
    )
    assert resp.status_code == 401
