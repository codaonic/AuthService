from fastapi import APIRouter, Depends, Form, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_event
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.oidc.access_tokens import decode_access_token, revoke_access_token
from app.oidc.clients import client_auth, get_and_validate_client
from app.oidc.refresh import revoke_refresh_token

router = APIRouter()


@router.post("/revoke", status_code=200)
async def revoke_token(
    request: Request,
    token: str = Form(...),
    token_type_hint: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """RFC 7009. Always answers 200, so it reveals nothing about the token;
    an app can only revoke tokens that were issued to it."""
    client_id, client_secret = client_auth(request, client_id, client_secret)
    await get_and_validate_client(db, client_id, client_secret, request)
    claims = decode_access_token(token)
    if claims is not None:
        if claims.get("client_id") == client_id:
            await revoke_access_token(redis, claims)
            log_event("token_revoked", client_id=client_id, token_type="access_token")
        return {}
    await revoke_refresh_token(db, redis, token, client_id=client_id)
    log_event("token_revoked", client_id=client_id)
    return {}
