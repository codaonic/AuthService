"""RFC 7662 token introspection: an app or API asks "is this token still
good?" and gets the answer as of now -- not just "the signature checks out".

A token stops being active the moment the person is signed out of that app,
loses access to it (directly or through a team), is disabled, or the token
is revoked. Callers authenticate as a confidential application.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.teams import roles_for
from app.db.models import Client
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.config import get_settings
from app.oidc.access_tokens import decode_access_token, still_valid
from app.oidc.clients import client_auth, get_and_validate_client
from app.oidc.refresh import REFRESH_KEY_PREFIX, _hash_token

router = APIRouter()

INACTIVE = {"active": False}


@router.post("/introspect")
@limiter.limit(get_settings().rate_limit_token)
async def introspect(
    request: Request,
    token: str = Form(...),
    token_type_hint: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client_id, client_secret = client_auth(request, client_id, client_secret)
    caller = await get_and_validate_client(db, client_id, client_secret, request)
    # A public app (a browser or phone app) has no secret, so anyone could
    # pose as it -- only a server-side app may ask about tokens.
    if caller.client_type != "confidential" and not caller.mtls_cert_thumbprint:
        raise HTTPException(401, "invalid_client: introspection needs a confidential application")

    claims = decode_access_token(token)
    if claims is not None:
        if not await still_valid(db, redis, claims):
            return INACTIVE
        response = {
            "active": True,
            "token_type": "Bearer",
            **{k: claims[k] for k in ("sub", "client_id", "scope", "aud", "iss", "exp", "iat", "jti") if k in claims},
        }
        if "email_verified" in claims:
            response["email_verified"] = claims["email_verified"]
        # Roles as they are now, not as they were when the token was made.
        issued_to = (await db.execute(select(Client).where(Client.client_id == claims["client_id"]))).scalar_one_or_none()
        if issued_to is not None and issued_to.roles_enabled and claims["sub"] != claims["client_id"]:
            response[issued_to.roles_claim or "roles"] = await roles_for(db, issued_to.client_id, claims["sub"])
        return response

    # A refresh token: only its own app may ask about it.
    data = await redis.hgetall(f"{REFRESH_KEY_PREFIX}{_hash_token(token)}")
    if data and data.get("client_id") == client_id:
        return {
            "active": True,
            "token_type": "refresh_token",
            "client_id": client_id,
            "sub": data["user_id"],
            "scope": data.get("scope", ""),
            "aud": data.get("resource", ""),
        }
    return INACTIVE
