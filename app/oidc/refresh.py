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
    auth_time: int | None = None,
    max_age: int | None = None,
) -> str:
    """`auth_time` + `max_age` cap the token at the application's sign-in
    timeout: it expires `max_age` seconds after the user authenticated, no
    matter how many times it is rotated in between.
    """
    settings = get_settings()
    token = secrets.token_urlsafe(48)
    token_hash = _hash_token(token)
    now = datetime.now(timezone.utc)
    ttl = settings.refresh_token_ttl_seconds
    if auth_time and max_age:
        ttl = max(1, min(ttl, auth_time + max_age - round(now.timestamp())))
    expires_at = now + timedelta(seconds=ttl)

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
            "auth_time": str(auth_time or ""),
        },
    )
    await redis.expire(f"{REFRESH_KEY_PREFIX}{token_hash}", ttl)
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
        "auth_time": int(data["auth_time"]) if data.get("auth_time") else None,
    }


async def refresh_token_owner(redis: Redis, refresh_token: str, client_id: str) -> str | None:
    """The user a live refresh token belongs to, if it was issued to `client_id`."""
    data = await redis.hgetall(f"{REFRESH_KEY_PREFIX}{_hash_token(refresh_token)}")
    if not data or data["client_id"] != client_id:
        return None
    return data["user_id"]


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


async def revoke_all_refresh_tokens_for_user(
    db: AsyncSession, redis: Redis, user_id: str, client_id: str | None = None
) -> None:
    """Kill every outstanding refresh token for a user -- used after a
    password reset. With `client_id`, only the ones issued to that
    application (a per-application logout).
    """
    query = select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    if client_id is not None:
        query = query.where(RefreshToken.client_id == client_id)
    result = await db.execute(query)
    rows = result.scalars().all()
    if not rows:
        return

    now = datetime.now(timezone.utc)
    for row in rows:
        row.revoked_at = now
    await db.commit()

    await redis.delete(*(f"{REFRESH_KEY_PREFIX}{row.token_hash}" for row in rows))
