import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import RefreshToken

REFRESH_KEY_PREFIX = "refresh:"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_refresh_token(
    db: AsyncSession,
    redis: Redis,
    user_id: str,
    client_id: str,
    resource: str,
    scope: str = "",
    rotated_from: str | None = None,
) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(48)
    token_hash = _hash_token(token)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.refresh_token_ttl_seconds)

    row = RefreshToken(
        user_id=user_id,
        client_id=client_id,
        resource_id=resource,
        scope=scope,
        token_hash=token_hash,
        rotated_from=rotated_from,
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()

    await redis.hset(
        f"{REFRESH_KEY_PREFIX}{token_hash}",
        mapping={
            "user_id": user_id,
            "client_id": client_id,
            "resource": resource,
            "scope": scope,
            "row_id": str(row.id),
        },
    )
    await redis.expire(f"{REFRESH_KEY_PREFIX}{token_hash}", settings.refresh_token_ttl_seconds)
    return token


async def validate_and_rotate_refresh_token(
    db: AsyncSession, redis: Redis, refresh_token: str, client_id: str
) -> dict:
    token_hash = _hash_token(refresh_token)
    key = f"{REFRESH_KEY_PREFIX}{token_hash}"
    data = await redis.hgetall(key)
    if not data or data["client_id"] != client_id:
        raise HTTPException(400, "invalid_grant")

    await redis.delete(key)

    row = await db.get(RefreshToken, uuid.UUID(data["row_id"]))
    if row is not None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.commit()

    return {
        "user_id": data["user_id"],
        "resource": data["resource"],
        "scope": data.get("scope", ""),
        "row_id": data["row_id"],
    }


async def revoke_refresh_token(db: AsyncSession, redis: Redis, refresh_token: str) -> None:
    token_hash = _hash_token(refresh_token)
    key = f"{REFRESH_KEY_PREFIX}{token_hash}"
    data = await redis.hgetall(key)
    await redis.delete(key)

    if data:
        row = await db.get(RefreshToken, uuid.UUID(data["row_id"]))
        if row is not None:
            row.revoked_at = datetime.now(timezone.utc)
            await db.commit()


async def revoke_all_refresh_tokens_for_user(db: AsyncSession, redis: Redis, user_id: str) -> None:
    """Kill every outstanding refresh token for a user -- used after a password reset."""
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    )
    rows = result.scalars().all()
    if not rows:
        return

    now = datetime.now(timezone.utc)
    for row in rows:
        row.revoked_at = now
    await db.commit()

    await redis.delete(*(f"{REFRESH_KEY_PREFIX}{row.token_hash}" for row in rows))
