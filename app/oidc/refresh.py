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
    sid: str | None = None,
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

    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(
            f"{REFRESH_KEY_PREFIX}{token_hash}",
            mapping={
                "user_id": user_id,
                "client_id": client_id,
                "resource": resource,
                "scope": scope,
                "row_id": str(row.id),
                "auth_time": str(auth_time or ""),
                "sid": sid or "",
            },
        )
        pipe.expire(f"{REFRESH_KEY_PREFIX}{token_hash}", ttl)
        await pipe.execute()
    return token


REPLAY_GRACE_SECONDS = 10


async def _treat_replay_as_theft(db: AsyncSession, redis: Redis, token_hash: str, client_id: str) -> None:
    """A refresh token that was already used (or revoked) is being presented
    again: either a thief or the real app is holding a stale copy. End that
    app's sign-in for the person so the stolen copy stops working. A retry
    within a few seconds is let through as an honest network repeat."""
    from app.audit import log_event

    row = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))).scalar_one_or_none()
    if row is None or row.client_id != client_id or row.revoked_at is None:
        return
    if (datetime.now(timezone.utc) - row.revoked_at.replace(tzinfo=row.revoked_at.tzinfo or timezone.utc)).total_seconds() < REPLAY_GRACE_SECONDS:
        return
    await revoke_all_refresh_tokens_for_user(db, redis, row.user_id, client_id)
    log_event("refresh_token_reuse", level=30, client_id=client_id, user_id=row.user_id)


async def validate_and_rotate_refresh_token(
    db: AsyncSession, redis: Redis, refresh_token: str, client_id: str
) -> dict:
    token_hash = _hash_token(refresh_token)
    key = f"{REFRESH_KEY_PREFIX}{token_hash}"
    # Read and delete in one step: a refresh token is single-use, even when
    # two requests race with it.
    async with redis.pipeline(transaction=True) as pipe:
        data, _ = await pipe.hgetall(key).delete(key).execute()
    if not data:
        await _treat_replay_as_theft(db, redis, token_hash, client_id)
        raise HTTPException(400, "invalid_grant")
    if data["client_id"] != client_id:
        raise HTTPException(400, "invalid_grant")

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
        "sid": data.get("sid") or None,
    }


async def refresh_token_owner(redis: Redis, refresh_token: str, client_id: str) -> str | None:
    """The user a live refresh token belongs to, if it was issued to `client_id`."""
    data = await redis.hgetall(f"{REFRESH_KEY_PREFIX}{_hash_token(refresh_token)}")
    if not data or data["client_id"] != client_id:
        return None
    return data["user_id"]


async def revoke_refresh_token(db: AsyncSession, redis: Redis, refresh_token: str, client_id: str | None = None) -> None:
    """With `client_id`, only a token issued to that app is revoked (RFC 7009:
    an app may revoke only its own tokens)."""
    token_hash = _hash_token(refresh_token)
    key = f"{REFRESH_KEY_PREFIX}{token_hash}"
    data = await redis.hgetall(key)
    if data and client_id is not None and data.get("client_id") != client_id:
        return
    await redis.delete(key)

    if data:
        row = await db.get(RefreshToken, uuid.UUID(data["row_id"]))
        if row is not None:
            row.revoked_at = datetime.now(timezone.utc)
            await db.commit()


async def revoke_all_refresh_tokens_for_user(
    db: AsyncSession,
    redis: Redis,
    user_id: str,
    client_id: str | None = None,
    *,
    sid: str | None = None,
    notify_apps: bool = True,
) -> None:
    """End a person's sign-in to one app (`client_id`) or to every app: their
    refresh tokens stop working, access tokens already handed out stop
    passing /introspect and /userinfo, and each affected app that has a
    back-channel logout URL is told so it can end its own session.

    Used for logout, an admin signing someone out, disabling an account, a
    password reset, losing access, and a stolen refresh token being reused.
    """
    from app.oidc import backchannel
    from app.oidc.access_tokens import cut_off_tokens

    await cut_off_tokens(redis, str(user_id), client_id)
    query = select(RefreshToken).where(RefreshToken.user_id == str(user_id), RefreshToken.revoked_at.is_(None))
    if client_id is not None:
        query = query.where(RefreshToken.client_id == client_id)
    rows = (await db.execute(query)).scalars().all()

    if rows:
        now = datetime.now(timezone.utc)
        for row in rows:
            row.revoked_at = now
        await db.commit()
        await redis.delete(*(f"{REFRESH_KEY_PREFIX}{row.token_hash}" for row in rows))

    if notify_apps:
        # The apps they were actually signed in to (or the one named).
        apps = {row.client_id for row in rows} | ({client_id} if client_id else set())
        await backchannel.notify(db, str(user_id), apps, sid=sid)
