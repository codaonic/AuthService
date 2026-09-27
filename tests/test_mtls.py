import pytest

from app.config import get_settings
from app.db.models import Client
from tests.helpers import create_client, create_resource

RESOURCE = "https://api.example.com"
THUMBPRINT = "AB:CD:EF:12:34:56:78:90".replace(":", "").lower()


async def _make_mtls_client(db_session, thumbprint=THUMBPRINT):
    client_row = await create_client(
        db_session,
        client_id="mtls-service",
        client_type="confidential",
        grant_types=("client_credentials",),
        client_secret="a-real-secret",
    )
    client_row.mtls_cert_thumbprint = thumbprint
    await db_session.commit()
    await create_resource(db_session, resource_id=RESOURCE)
    return client_row


@pytest.mark.asyncio
async def test_mtls_disabled_by_default_even_with_correct_headers(client, db_session):
    await _make_mtls_client(db_session)

    resp = await client.post(
        "/token",
        data={"grant_type": "client_credentials", "client_id": "mtls-service", "resource": RESOURCE},
        headers={
            "X-Internal-Proxy-Secret": "whatever",
            "X-Client-Cert-Verify": "SUCCESS",
            "X-Client-Cert-Fingerprint": THUMBPRINT,
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mtls_succeeds_with_correct_headers_and_no_client_secret(client, db_session, monkeypatch):
    monkeypatch.setenv("MTLS_TRUSTED_PROXY_SECRET", "proxy-secret-123")
    get_settings.cache_clear()
    try:
        await _make_mtls_client(db_session)

        resp = await client.post(
            "/token",
            data={"grant_type": "client_credentials", "client_id": "mtls-service", "resource": RESOURCE},
            headers={
                "X-Internal-Proxy-Secret": "proxy-secret-123",
                "X-Client-Cert-Verify": "SUCCESS",
                "X-Client-Cert-Fingerprint": THUMBPRINT,
            },
        )
        assert resp.status_code == 200, resp.text
        assert "access_token" in resp.json()
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_mtls_rejects_wrong_fingerprint(client, db_session, monkeypatch):
    monkeypatch.setenv("MTLS_TRUSTED_PROXY_SECRET", "proxy-secret-123")
    get_settings.cache_clear()
    try:
        await _make_mtls_client(db_session)

        resp = await client.post(
            "/token",
            data={"grant_type": "client_credentials", "client_id": "mtls-service", "resource": RESOURCE},
            headers={
                "X-Internal-Proxy-Secret": "proxy-secret-123",
                "X-Client-Cert-Verify": "SUCCESS",
                "X-Client-Cert-Fingerprint": "0" * len(THUMBPRINT),
            },
        )
        assert resp.status_code == 401
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_mtls_rejects_missing_proxy_secret_even_with_matching_fingerprint(client, db_session, monkeypatch):
    """Guards against a request reaching the app directly and self-declaring
    a verified certificate -- the proxy secret is what makes the cert
    headers trustworthy at all."""
    monkeypatch.setenv("MTLS_TRUSTED_PROXY_SECRET", "proxy-secret-123")
    get_settings.cache_clear()
    try:
        await _make_mtls_client(db_session)

        resp = await client.post(
            "/token",
            data={"grant_type": "client_credentials", "client_id": "mtls-service", "resource": RESOURCE},
            headers={
                "X-Client-Cert-Verify": "SUCCESS",
                "X-Client-Cert-Fingerprint": THUMBPRINT,
            },
        )
        assert resp.status_code == 401
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_mtls_client_secret_alone_is_not_sufficient_once_mtls_configured(client, db_session):
    """Once a client has an mTLS thumbprint registered, a correct
    client_secret alone must not be enough -- mTLS becomes required, not
    an optional alternative, or it wouldn't add any real security."""
    await _make_mtls_client(db_session)

    resp = await client.post(
        "/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "mtls-service",
            "client_secret": "a-real-secret",
            "resource": RESOURCE,
        },
    )
    assert resp.status_code == 401
