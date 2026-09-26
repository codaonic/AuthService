from fastapi import APIRouter, Depends, Form
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.redis_client import get_redis
from app.db.session import get_db
from app.oidc.clients import get_and_validate_client
from app.oidc.refresh import revoke_refresh_token

router = APIRouter()


@router.post("/revoke", status_code=200)
async def revoke_token(
    token: str = Form(...),
    token_type_hint: str | None = Form(None),
    client_id: str = Form(...),
    client_secret: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    await get_and_validate_client(db, client_id, client_secret)
    await revoke_refresh_token(db, redis, token)
    return {}
