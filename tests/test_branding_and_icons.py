from pathlib import Path
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_root_favicon_ico_endpoint(client: AsyncClient):
    resp = await client.get("/favicon.ico")
    assert resp.status_code == 200
    assert "image/x-icon" in resp.headers.get("content-type", "")
    assert len(resp.content) > 0

@pytest.mark.asyncio
async def test_root_favicon_svg_endpoint(client: AsyncClient):
    resp = await client.get("/favicon.svg")
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers.get("content-type", "")
    assert "<svg" in resp.text

@pytest.mark.asyncio
async def test_admin_favicon_and_logo_assets(client: AsyncClient):
    # Test that SPA route handler serves static assets directly from dist
    resp_svg = await client.get("/admin/favicon.svg")
    assert resp_svg.status_code == 200
    assert "<svg" in resp_svg.text

    resp_ico = await client.get("/admin/favicon.ico")
    assert resp_ico.status_code == 200
    assert len(resp_ico.content) > 0

@pytest.mark.asyncio
async def test_base_html_includes_brand_favicon(client: AsyncClient, db_session):
    from tests.helpers import create_client, create_resource, make_pkce_pair
    await create_client(db_session, client_id="brand-client", redirect_uris=("https://example.com/cb",))
    await create_resource(db_session, resource_id="https://api.example.com")
    _, challenge = make_pkce_pair()

    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "brand-client",
            "redirect_uri": "https://example.com/cb",
            "resource": "https://api.example.com",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "profile email",
        },
    )
    assert resp.status_code == 200
    assert "favicon.svg" in resp.text
    assert "favicon.ico" in resp.text
    assert "apple-touch-icon.png" in resp.text
    assert "Auth Service" in resp.text
    assert "OAuth 2.1" in resp.text
