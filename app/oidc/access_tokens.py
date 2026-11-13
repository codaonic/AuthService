"""Checking an access token the service issued: is it genuine, and is it
still good right now?

An access token is a signed JWT that lives a few minutes, so an API that
only checks the signature keeps accepting it until it expires, even after
the person was signed out or lost access. `still_valid` closes that gap for
anyone who asks the service (/introspect, /userinfo): it re-checks the
person, the app and their access live, and honours "cut-off" times set when
tokens are revoked.
"""

import time
import uuid

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwt import JWTClaimsRegistry
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Client, Resource, User
from app.db.tenant import bypass_tenant_rls
from app.oidc.keys import get_key_manager

CUTOFF_PREFIX = "token_cutoff:"
REVOKED_JTI_PREFIX = "revoked_jti:"
ACCESS_TOKEN_TYPE = "at+jwt"  # RFC 9068


def _cutoff_keys(user_id: str, client_id: str) -> tuple[str, str]:
    return f"{CUTOFF_PREFIX}{user_id}", f"{CUTOFF_PREFIX}{user_id}:{client_id}"


async def cut_off_tokens(redis: Redis, user_id: str, client_id: str | None = None) -> None:
    """Access tokens issued before now stop passing /introspect and
    /userinfo -- for one app, or every app when `client_id` is None.
    Kept only as long as a token issued now could live."""
    key = f"{CUTOFF_PREFIX}{user_id}" + (f":{client_id}" if client_id else "")
    # Sub-second, so a token issued in the same second as a logout (iat is
    # whole seconds) still counts as issued before it.
    await redis.set(key, f"{time.time():.3f}", ex=get_settings().access_token_ttl_seconds + 60)


async def revoke_access_token(redis: Redis, claims: dict) -> None:
    """This one access token stops passing /introspect and /userinfo."""
    ttl = int(claims.get("exp", 0)) - int(time.time())
    if claims.get("jti") and ttl > 0:
        await redis.set(f"{REVOKED_JTI_PREFIX}{claims['jti']}", "1", ex=ttl)


def decode_access_token(token: str) -> dict | None:
    """The claims of a genuine, unexpired access token from this service;
    None for anything else -- including ID tokens, which are signed with the
    same key but are for the app, not for calling APIs."""
    settings = get_settings()
    try:
        verified = jwt.decode(token, get_key_manager().public_key_set(), algorithms=[settings.signing_key_algorithm])
        JWTClaimsRegistry(iss={"essential": True, "value": settings.issuer_url}, exp={"essential": True}).validate(
            verified.claims
        )
    except (JoseError, ValueError):
        return None
    claims = verified.claims
    if verified.header.get("typ") not in (ACCESS_TOKEN_TYPE, None):
        return None
    if "client_id" not in claims or "at_hash" in claims or "nonce" in claims:
        return None
    return claims


async def still_valid(db: AsyncSession, redis: Redis, claims: dict) -> bool:
    """Would this token be issued again right now?"""
    client_id = claims.get("client_id")
    subject = claims.get("sub")
    if claims.get("jti") and await redis.exists(f"{REVOKED_JTI_PREFIX}{claims['jti']}"):
        return False
    client = (await db.execute(select(Client).where(Client.client_id == client_id))).scalar_one_or_none()
    if client is None or not client.enabled:
        return False

    resource = claims.get("aud")
    if isinstance(resource, str) and resource:
        registered = (await db.execute(select(Resource).where(Resource.resource_id == resource))).scalar_one_or_none()
        if registered is not None and not registered.enabled:
            return False

    if subject == client_id:  # client_credentials: no person behind it
        return True
    try:
        user_id = uuid.UUID(subject)
    except (TypeError, ValueError):
        return False
    await bypass_tenant_rls(db)
    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        return False

    issued = int(claims.get("iat", 0))
    for cutoff in await redis.mget(*_cutoff_keys(str(user_id), client_id)):
        if cutoff and issued < float(cutoff):
            return False

    from app.oidc.authorize import _has_client_access, _user_can_access_client

    if not await _user_can_access_client(db, user, client):
        return False
    if client.restrict_access and not await _has_client_access(db, client_id, str(user_id)):
        return False
    return True
