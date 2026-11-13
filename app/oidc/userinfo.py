import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.teams import roles_for
from app.db.models import Client, User
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.db.tenant import bypass_tenant_rls
from app.oidc.access_tokens import decode_access_token, still_valid
from app.oidc.id_token import profile_claims

router = APIRouter()


def _get_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "missing_or_invalid_authorization_header")
    return auth_header.removeprefix("Bearer ").strip()


@router.get("/userinfo")
@router.post("/userinfo")
async def userinfo(request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    claims = decode_access_token(_get_bearer_token(request))
    if claims is None:
        raise HTTPException(401, "invalid_token")
    try:
        user_id = uuid.UUID(claims["sub"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, "invalid_token: not a user token") from exc
    # Signed out, lost access, or the token was revoked: not just expired.
    if not await still_valid(db, redis, claims):
        raise HTTPException(401, "invalid_token")

    await bypass_tenant_rls(db)
    user = await db.get(User, user_id)
    scope = set(claims.get("scope", "").split())
    # email and email_verified were always returned here; kept for existing apps.
    response = {"sub": str(user.id), "email": user.email, "email_verified": user.email_verified}
    response.update(profile_claims(user, scope))

    # Only for apps that turned roles on -- most never define any.
    client = (await db.execute(select(Client).where(Client.client_id == claims.get("client_id")))).scalar_one_or_none()
    if client is not None and client.roles_enabled:
        # Their own roles, their teams' roles, and everything those include.
        response[client.roles_claim or "roles"] = await roles_for(db, client.client_id, user.id)
    return response
