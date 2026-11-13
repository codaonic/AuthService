import base64
from urllib.parse import unquote

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_event
from app.auth.passwords import verify_client_secret
from app.config import get_settings
from app.db.models import Client
from app.oidc.cimd import is_cimd_client_id, resolve_cimd_client


def _mtls_verified(request: Request | None, expected_thumbprint: str) -> bool:
    """Check the reverse proxy's mTLS verification headers against the
    client's registered certificate thumbprint.

    These headers are only trustworthy because the proxy also sets a shared
    secret this app checks for -- without that, any request reaching the
    app directly could just claim `X-Client-Cert-Verify: SUCCESS` itself.
    See `mtls_trusted_proxy_secret` in config, and the nginx config it
    depends on.
    """
    settings = get_settings()
    if not settings.mtls_trusted_proxy_secret or request is None:
        return False
    if request.headers.get("X-Internal-Proxy-Secret") != settings.mtls_trusted_proxy_secret:
        return False
    if request.headers.get("X-Client-Cert-Verify") != "SUCCESS":
        return False
    fingerprint = request.headers.get("X-Client-Cert-Fingerprint", "")
    return bool(fingerprint) and fingerprint.lower() == expected_thumbprint.lower()


async def get_and_validate_client(
    db: AsyncSession, client_id: str, client_secret: str | None, request: Request | None = None
) -> Client:
    if is_cimd_client_id(client_id):
        client = await resolve_cimd_client(db, client_id)
        if client_secret:  # CIMD clients are always public -- no secret to check
            raise HTTPException(401, "invalid_client")
        if not client.enabled:
            raise HTTPException(401, "invalid_client")
        return client

    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(401, "invalid_client")
    if not client.enabled:
        raise HTTPException(401, "invalid_client")

    if client.mtls_cert_thumbprint:
        # mTLS is a stronger binding than a shared secret (it proves
        # possession of a private key, not just knowledge of a string) --
        # once configured for a client, it's required, not optional.
        if not _mtls_verified(request, client.mtls_cert_thumbprint):
            log_event("mtls_auth_failed", client_id=client_id)
            raise HTTPException(401, "invalid_client: mTLS client certificate required")
        return client

    if client.client_type == "confidential":
        if not client_secret or client.client_secret_hash is None:
            raise HTTPException(401, "invalid_client")
        if not await verify_client_secret(client_secret, client.client_secret_hash):
            raise HTTPException(401, "invalid_client")
    elif client_secret:
        raise HTTPException(401, "invalid_client")

    return client


def client_auth(request: Request, client_id: str | None, client_secret: str | None) -> tuple[str, str | None]:
    """The client's id and secret, from the form body (client_secret_post) or
    an `Authorization: Basic` header (client_secret_basic, the default in
    most OAuth libraries). Using both at once, or two different ids, is refused.
    """
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        if not client_id:
            raise HTTPException(401, "invalid_client")
        return client_id, client_secret
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode()
        basic_id, _, basic_secret = decoded.partition(":")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(401, "invalid_client")
    basic_id, basic_secret = unquote(basic_id), unquote(basic_secret)
    if client_secret or (client_id and client_id != basic_id) or not basic_id:
        raise HTTPException(401, "invalid_client")
    return basic_id, basic_secret or None
