"""OpenID Connect Back-Channel Logout 1.0, one app at a time.

When someone is signed out of an app (by themselves, by an admin, by losing
access to it, or because their account was disabled or their password
reset), the service tells that app's server directly with a signed
`logout_token`, so the app ends its own session even if the browser is
closed. Only the apps the person is being signed out of are told; the
others in the login group stay signed in.

Sending happens in the background and never holds up the request that
caused it. A failure is logged, not retried.
"""

import asyncio
import ipaddress
import time
import uuid
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from joserfc import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_event
from app.config import get_settings
from app.db.models import Client
from app.oidc.keys import get_key_manager

EVENT = "http://schemas.openid.net/event/backchannel-logout"
TIMEOUT_SECONDS = 5

# Background sends still running, so they aren't garbage-collected mid-flight.
_in_flight: set[asyncio.Task] = set()


def check_logout_uri(uri: str) -> str | None:
    """A back-channel logout URL an admin typed: https, or plain http only for
    this machine or a private network address. Blank clears it."""
    uri = uri.strip()
    if not uri:
        return None
    parts = urlsplit(uri)
    if parts.fragment or not parts.hostname:
        raise HTTPException(400, "The back-channel logout URL must be a full URL without a #fragment")
    if parts.scheme == "https":
        return uri
    if parts.scheme == "http":
        host = parts.hostname
        try:
            local = host == "localhost" or host.endswith(".localhost") or ipaddress.ip_address(host).is_private
        except ValueError:
            local = False
        if local:
            return uri
    raise HTTPException(400, "The back-channel logout URL must use https (http only for localhost or a private address)")


def logout_token(client_id: str, user_id: str, sid: str | None) -> str:
    settings = get_settings()
    kid, key = get_key_manager().signing_key()
    now = int(time.time())
    payload = {
        "iss": settings.issuer_url,
        "aud": client_id,
        "iat": now,
        "exp": now + 120,
        "jti": str(uuid.uuid4()),
        "sub": user_id,
        "events": {EVENT: {}},
    }
    if sid:
        payload["sid"] = sid
    return jwt.encode(
        {"alg": settings.signing_key_algorithm, "kid": kid, "typ": "logout+jwt"},
        payload,
        key,
        algorithms=[settings.signing_key_algorithm],
    )


async def _send(uri: str, token: str) -> int:
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as http:
        response = await http.post(uri, data={"logout_token": token}, headers={"Cache-Control": "no-store"})
        return response.status_code


async def _deliver(client_id: str, uri: str, user_id: str, sid: str | None) -> None:
    try:
        status = await _send(uri, logout_token(client_id, user_id, sid))
        ok = 200 <= status < 300
        log_event(
            "backchannel_logout_sent" if ok else "backchannel_logout_failed",
            level=20 if ok else 30,
            client_id=client_id,
            user_id=user_id,
            status=status,
        )
    except Exception as exc:  # network trouble must never break the sign-out itself
        log_event("backchannel_logout_failed", level=30, client_id=client_id, user_id=user_id, reason=type(exc).__name__)


async def notify(db: AsyncSession, user_id: str, client_ids: set[str], sid: str | None = None) -> None:
    """Tell each of these apps that has a back-channel logout URL."""
    if not client_ids:
        return
    rows = await db.execute(
        select(Client.client_id, Client.backchannel_logout_uri).where(
            Client.client_id.in_(client_ids), Client.backchannel_logout_uri.is_not(None)
        )
    )
    for client_id, uri in rows.all():
        if not uri:
            continue
        task = asyncio.create_task(_deliver(client_id, uri, str(user_id), sid))
        _in_flight.add(task)
        task.add_done_callback(_in_flight.discard)


async def wait_for_deliveries() -> None:
    """For tests and shutdown: let sends already started finish."""
    if _in_flight:
        await asyncio.gather(*list(_in_flight), return_exceptions=True)
