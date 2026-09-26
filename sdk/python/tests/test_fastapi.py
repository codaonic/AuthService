import httpx
import pytest
from fastapi import Depends, FastAPI

from auth_service_sdk import TokenValidator
from auth_service_sdk.fastapi import make_auth_dependency, make_scope_dependency
from auth_service_sdk.protected_resource import protected_resource_router
from tests.helpers import ISSUER, RESOURCE_ID, make_token


def _make_app(mock_transport):
    validator = TokenValidator(
        issuer=ISSUER,
        resource_id=RESOURCE_ID,
        jwks_url="https://auth.example.com/jwks.json",
        http_client=httpx.Client(transport=mock_transport),
    )
    require_auth = make_auth_dependency(validator)
    require_profile_scope = make_scope_dependency(validator, "profile")

    app = FastAPI()
    app.include_router(protected_resource_router(RESOURCE_ID, ISSUER, resource_name="Example API"))

    @app.get("/me")
    async def me(claims: dict = Depends(require_auth)):
        return {"sub": claims["sub"]}

    @app.get("/profile")
    async def profile(claims: dict = Depends(require_profile_scope)):
        return {"sub": claims["sub"]}

    return app


@pytest.mark.asyncio
async def test_missing_token_returns_401_with_challenge(mock_transport):
    app = _make_app(mock_transport)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/me")

    assert resp.status_code == 401
    assert "resource_metadata=" in resp.headers["WWW-Authenticate"]


@pytest.mark.asyncio
async def test_valid_token_allows_access(keypair, mock_transport):
    app = _make_app(mock_transport)
    token = make_token(keypair, sub="user-1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json() == {"sub": "user-1"}


@pytest.mark.asyncio
async def test_missing_scope_returns_403(keypair, mock_transport):
    app = _make_app(mock_transport)
    token = make_token(keypair, scope="email")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/profile", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_protected_resource_metadata(mock_transport):
    app = _make_app(mock_transport)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/.well-known/oauth-protected-resource")

    assert resp.status_code == 200
    body = resp.json()
    assert body["resource"] == RESOURCE_ID
    assert body["authorization_servers"] == [ISSUER]
